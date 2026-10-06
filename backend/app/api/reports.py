"""Reports API (spec §10.5): scheduled report definitions, runs, custom-prompt reports."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import schemas as A
from app.analytics.audit import audit
from app.analytics.reports import new_run, parse_smtp_url
from app.analytics.schedule import next_run, period_for
from app.auth.platform import for_viewer
from app.deps import (
    Db,
    OrgAdmin,
    OrgMember,
    PlatformOwner,
    SettingsDep,
    get_queue,
    get_redis,
)
from app.errors import api_error
from app.models import Organization, Report, ReportRun, Repository, User
from app.settings import Settings
from app.worker.queue import TaskQueue

router = APIRouter()
RUN_TASK = "reports.run"
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")


def def_out(r: Report) -> A.ReportDef:
    return A.ReportDef(
        id=str(r.id),
        name=r.name,
        prompt=r.prompt,
        schedule=r.schedule,
        hour_utc=r.hour_utc,
        weekday=r.weekday,
        repo_ids=list(r.repo_ids or []),
        email_to=list(r.email_to or []),
        enabled=r.enabled,
        next_run_at=r.next_run_at,
        last_run_at=r.last_run_at,
        created_at=r.created_at,
    )


def run_summary(r: ReportRun) -> A.ReportRunSummary:
    return A.ReportRunSummary(
        id=str(r.id),
        report_id=str(r.report_id) if r.report_id else None,
        title=r.title,
        trigger=r.trigger,
        status=r.status,
        period_start=r.period_start,
        period_end=r.period_end,
        degraded=r.degraded,
        created_at=r.created_at,
        finished_at=r.finished_at,
    )


def run_detail(r: ReportRun) -> A.ReportRunDetail:
    return A.ReportRunDetail(
        **run_summary(r).model_dump(),
        prompt=r.prompt,
        content=r.content,
        error=r.error,
        emailed_to=list(r.emailed_to or []),
        input_tokens=r.input_tokens,
        output_tokens=r.output_tokens,
        cost_usd=r.cost_usd,
    )


async def check_repo_ids(db: AsyncSession, org_id: UUID, raw: list[str]) -> list[str]:
    ids: list[UUID] = []
    for r in raw:
        try:
            ids.append(UUID(r))
        except ValueError as exc:
            raise api_error(422, "invalid_repo", f"Unknown repository {r!r}") from exc
    if not ids:
        return []
    found = set(
        (
            await db.execute(
                select(Repository.id).where(Repository.org_id == org_id, Repository.id.in_(ids))
            )
        ).scalars()
    )
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise api_error(422, "invalid_repo", f"Unknown repository {missing[0]}")
    return [str(i) for i in ids]


def check_emails(raw: list[str]) -> list[str]:
    out = []
    for e in raw:
        e = e.strip()
        if not e:
            continue
        if not EMAIL_RE.match(e) or len(e) > 320:
            raise api_error(422, "invalid_email", f"Invalid email address {e!r}")
        out.append(e)
    return sorted(set(out))


async def _own(db: AsyncSession, org_id: UUID, report_id: UUID) -> Report:
    r = (
        await db.execute(select(Report).where(Report.id == report_id, Report.org_id == org_id))
    ).scalar_one_or_none()
    if r is None:
        raise api_error(404, "not_found", "Report not found")
    return r


@router.get("/api/orgs/{org_slug}/reports", response_model=A.ReportDefList)
async def list_reports(ctx: OrgMember, db: Db, settings: SettingsDep) -> A.ReportDefList:
    rows = (
        await db.execute(
            select(Report).where(Report.org_id == ctx.org.id).order_by(Report.created_at)
        )
    ).scalars()
    return A.ReportDefList(
        reports=[def_out(r) for r in rows],
        email_enabled=parse_smtp_url(settings.smtp_url.get_secret_value()) is not None,
    )


async def _apply(db: AsyncSession, org_id: UUID, r: Report, body: A.ReportDefIn) -> None:
    r.name, r.prompt, r.schedule = body.name.strip(), body.prompt.strip(), body.schedule
    r.hour_utc, r.weekday, r.enabled = body.hour_utc, body.weekday, body.enabled
    r.repo_ids = await check_repo_ids(db, org_id, body.repo_ids)
    r.email_to = check_emails(body.email_to)
    r.next_run_at = (
        next_run(r.schedule, r.hour_utc, r.weekday, datetime.now(UTC)) if r.enabled else None
    )


@router.post("/api/orgs/{org_slug}/reports", response_model=A.ReportDef, status_code=201)
async def create_report(body: A.ReportDefIn, ctx: OrgAdmin, db: Db) -> A.ReportDef:
    r = Report(org_id=ctx.org.id, created_by_user_id=ctx.user.id)
    await _apply(db, ctx.org.id, r, body)
    db.add(r)
    await db.flush()
    audit(
        db,
        ctx.org.id,
        "report.created",
        actor=ctx.user,
        target_type="report",
        target_id=r.id,
        details={"name": r.name, "schedule": r.schedule},
    )
    await db.commit()
    await db.refresh(r)
    return def_out(r)


@router.put("/api/orgs/{org_slug}/reports/{report_id}", response_model=A.ReportDef)
async def update_report(report_id: UUID, body: A.ReportDefIn, ctx: OrgAdmin, db: Db) -> A.ReportDef:
    r = await _own(db, ctx.org.id, report_id)
    await _apply(db, ctx.org.id, r, body)
    audit(
        db,
        ctx.org.id,
        "report.updated",
        actor=ctx.user,
        target_type="report",
        target_id=r.id,
        details={"name": r.name, "schedule": r.schedule, "enabled": r.enabled},
    )
    await db.commit()
    await db.refresh(r)
    return def_out(r)


@router.delete("/api/orgs/{org_slug}/reports/{report_id}", status_code=204)
async def delete_report(report_id: UUID, ctx: OrgAdmin, db: Db) -> Response:
    r = await _own(db, ctx.org.id, report_id)
    audit(
        db,
        ctx.org.id,
        "report.deleted",
        actor=ctx.user,
        target_type="report",
        target_id=r.id,
        details={"name": r.name},
    )
    await db.delete(r)
    await db.commit()
    return Response(status_code=204)


@router.post(
    "/api/orgs/{org_slug}/reports/{report_id}/run",
    response_model=A.ReportRunSummary,
    status_code=202,
)
async def run_report_now(
    report_id: UUID, request: Request, ctx: OrgAdmin, db: Db
) -> A.ReportRunSummary:
    r = await _own(db, ctx.org.id, report_id)
    since, until = period_for(r.schedule, datetime.now(UTC))
    run = new_run(
        r,
        org_id=ctx.org.id,
        title=f"{r.name} — {until:%Y-%m-%d}",
        prompt=r.prompt,
        trigger="manual",
        since=since,
        until=until,
        repo_ids=list(r.repo_ids),
        user_id=ctx.user.id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    get_queue(request).enqueue(RUN_TASK, str(run.id))
    return run_summary(run)


# --- custom-prompt reports ----------------------------------------------------------------


async def take_custom_slot(redis: Redis, org_id: UUID, per_day: int) -> bool:
    """Fixed UTC-day counter; ``per_day == 0`` disables custom reports."""
    if per_day <= 0:
        return False
    key = f"reports:custom:{org_id}:{datetime.now(UTC):%Y%m%d}"
    n = int(await redis.incr(key))
    if n == 1:
        await redis.expire(key, 2 * 86400)
    if n > per_day:
        await redis.decr(key)
        return False
    return True


async def create_custom_run(
    db: AsyncSession,
    redis: Redis,
    queue: TaskQueue,
    settings: Settings,
    org: Organization,
    body: A.CustomReportIn,
    user: User | None,
    actor_label: str | None = None,
) -> ReportRun:
    repo_ids = await check_repo_ids(db, org.id, body.repo_ids)
    if not await take_custom_slot(redis, org.id, settings.reports_custom_per_day):
        raise api_error(
            429,
            "report_limit",
            f"Custom reports are limited to {settings.reports_custom_per_day} per day",
        )
    until = datetime.now(UTC)
    title = (body.title or "").strip() or f"Custom report — {until:%Y-%m-%d}"
    run = new_run(
        None,
        org_id=org.id,
        title=title,
        prompt=body.prompt.strip(),
        trigger="custom",
        since=until - timedelta(days=body.days),
        until=until,
        repo_ids=repo_ids,
        user_id=user.id if user else None,
    )
    db.add(run)
    await db.flush()
    audit(
        db,
        org.id,
        "report.custom_requested",
        actor=user,
        actor_label=actor_label,
        target_type="report_run",
        target_id=run.id,
        details={"days": body.days},
    )
    await db.commit()
    await db.refresh(run)
    queue.enqueue(RUN_TASK, str(run.id))
    return run


@router.post(
    "/api/orgs/{org_slug}/reports/custom", response_model=A.ReportRunSummary, status_code=202
)
async def custom_report(
    body: A.CustomReportIn, request: Request, ctx: OrgMember, db: Db, settings: SettingsDep
) -> A.ReportRunSummary:
    run = await create_custom_run(
        db, get_redis(request), get_queue(request), settings, ctx.org, body, ctx.user
    )
    return run_summary(run)


async def list_runs(
    db: AsyncSession, org_id: UUID, limit: int, before: datetime | None
) -> A.ReportRunList:
    q = select(ReportRun).where(ReportRun.org_id == org_id)
    if before is not None:
        q = q.where(ReportRun.created_at < before)
    rows = list(
        (await db.execute(q.order_by(ReportRun.created_at.desc()).limit(limit + 1))).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return A.ReportRunList(
        runs=[run_summary(r) for r in rows],
        next_before=rows[-1].created_at if more and rows else None,
    )


async def get_run(db: AsyncSession, org_id: UUID, run_id: UUID) -> ReportRun:
    r = (
        await db.execute(
            select(ReportRun).where(ReportRun.id == run_id, ReportRun.org_id == org_id)
        )
    ).scalar_one_or_none()
    if r is None:
        raise api_error(404, "not_found", "Report run not found")
    return r


@router.get("/api/orgs/{org_slug}/report-runs", response_model=A.ReportRunList)
async def report_runs(
    ctx: OrgMember,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: datetime | None = None,
) -> A.ReportRunList:
    return await list_runs(db, ctx.org.id, limit, before)


@router.get("/api/orgs/{org_slug}/report-runs/{run_id}", response_model=A.ReportRunDetail)
async def report_run(
    run_id: UUID, ctx: OrgMember, db: Db, owner: PlatformOwner
) -> A.ReportRunDetail:
    return for_viewer(run_detail(await get_run(db, ctx.org.id, run_id)), owner)
