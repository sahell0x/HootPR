"""Dashboard analytics, review usage and data export (spec §10.5)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import schemas as A
from app.analytics.audit import audit
from app.analytics.export import to_csv, to_json
from app.analytics.metrics import Scope, compute_metrics, compute_usage
from app.auth.platform import INTERNAL_FIELDS, for_viewer
from app.deps import Db, OrgMember, PlatformOwner, SettingsDep
from app.errors import api_error
from app.models import (
    AuditLog,
    CreditLedgerEntry,
    Finding,
    Organization,
    PullRequest,
    Repository,
    Review,
)

router = APIRouter()

Days = Annotated[int, Query(ge=1, le=365)]
ExportKind = Literal["reviews", "findings", "usage", "audit"]
ExportFormat = Literal["csv", "json"]


async def scope_for(db: AsyncSession, org: Organization, days: int, repo_id: UUID | None) -> Scope:
    if repo_id is not None:
        owned = (
            await db.execute(
                select(Repository.id).where(Repository.id == repo_id, Repository.org_id == org.id)
            )
        ).scalar_one_or_none()
        if owned is None:
            raise api_error(404, "not_found", "Repository not found")
    until = datetime.now(UTC)
    return Scope(org.id, until - timedelta(days=days), until, (repo_id,) if repo_id else ())


async def org_metrics(
    db: AsyncSession, org: Organization, days: int, repo_id: UUID | None
) -> A.Metrics:
    return await compute_metrics(db, await scope_for(db, org, days, repo_id), days)


async def org_usage(
    db: AsyncSession, org: Organization, days: int, repo_id: UUID | None
) -> A.Usage:
    return await compute_usage(db, await scope_for(db, org, days, repo_id), days)


@router.get("/api/orgs/{org_slug}/analytics/metrics", response_model=A.Metrics)
async def metrics(
    ctx: OrgMember, db: Db, owner: PlatformOwner, days: Days = 30, repo_id: UUID | None = None
) -> A.Metrics:
    return for_viewer(await org_metrics(db, ctx.org, days, repo_id), owner)


@router.get("/api/orgs/{org_slug}/analytics/usage", response_model=A.Usage)
async def usage(
    ctx: OrgMember, db: Db, owner: PlatformOwner, days: Days = 30, repo_id: UUID | None = None
) -> A.Usage:
    return for_viewer(await org_usage(db, ctx.org, days, repo_id), owner)


# --- export ---------------------------------------------------------------------------------

REVIEW_COLUMNS = [
    "id",
    "created_at",
    "finished_at",
    "repository",
    "pr_number",
    "pr_title",
    "pr_author",
    "trigger",
    "status",
    "skip_reason",
    "head_sha",
    "files_reviewed",
    "findings_posted",
    "credits_charged",
    "input_tokens",
    "cached_tokens",
    "output_tokens",
    "cost_usd",
]
FINDING_COLUMNS = [
    "id",
    "created_at",
    "review_id",
    "repository",
    "pr_number",
    "path",
    "start_line",
    "end_line",
    "severity",
    "category",
    "title",
    "source",
    "confidence",
    "judge_verdict",
    "posted",
    "status",
]
USAGE_COLUMNS = ["id", "created_at", "delta", "reason", "ref_type", "ref_id", "balance_after"]
AUDIT_COLUMNS = [
    "id",
    "created_at",
    "actor_label",
    "action",
    "target_type",
    "target_id",
    "details",
]


async def export_rows(
    db: AsyncSession,
    org_id: UUID,
    kind: ExportKind,
    since: datetime,
    limit: int,
    *,
    internal: bool = False,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Export rows. LLM tokens / cost columns only when ``internal`` (platform owners)."""
    if kind == "reviews":
        q = (
            select(Review, PullRequest, Repository.full_name)
            .join(PullRequest, PullRequest.id == Review.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .where(Review.org_id == org_id, Review.created_at >= since)
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
        rows = [
            {
                "id": r.id,
                "created_at": r.created_at,
                "finished_at": r.finished_at,
                "repository": name,
                "pr_number": pr.number,
                "pr_title": pr.title,
                "pr_author": pr.author_username,
                "trigger": r.trigger,
                "status": r.status,
                "skip_reason": r.skip_reason,
                "head_sha": r.head_sha,
                "files_reviewed": r.files_reviewed,
                "findings_posted": r.findings_posted,
                "credits_charged": r.credits_charged,
                "input_tokens": r.input_tokens,
                "cached_tokens": r.cached_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": r.cost_usd,
            }
            for r, pr, name in (await db.execute(q)).all()
        ]
        if internal:
            return REVIEW_COLUMNS, rows
        cols = [c for c in REVIEW_COLUMNS if c not in INTERNAL_FIELDS]
        return cols, [{c: row[c] for c in cols} for row in rows]
    if kind == "findings":
        frows: list[dict[str, Any]]
        fq = (
            select(Finding, PullRequest.number, Repository.full_name)
            .join(Review, Review.id == Finding.review_id)
            .join(PullRequest, PullRequest.id == Review.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .where(Review.org_id == org_id, Finding.created_at >= since)
            .order_by(Finding.created_at.desc())
            .limit(limit)
        )
        frows = [
            {
                "id": f.id,
                "created_at": f.created_at,
                "review_id": f.review_id,
                "repository": name,
                "pr_number": num,
                "path": f.path,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "source": f.source,
                "confidence": f.confidence,
                "judge_verdict": f.judge_verdict,
                "posted": f.posted,
                "status": f.status,
            }
            for f, num, name in (await db.execute(fq)).all()
        ]
        return FINDING_COLUMNS, frows
    if kind == "usage":
        lq = (
            select(CreditLedgerEntry)
            .where(CreditLedgerEntry.org_id == org_id, CreditLedgerEntry.created_at >= since)
            .order_by(CreditLedgerEntry.created_at.desc())
            .limit(limit)
        )
        rows = [{c: getattr(e, c) for c in USAGE_COLUMNS} for e in (await db.execute(lq)).scalars()]
        return USAGE_COLUMNS, rows
    aq = (
        select(AuditLog)
        .where(AuditLog.org_id == org_id, AuditLog.created_at >= since)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    rows = [{c: getattr(e, c) for c in AUDIT_COLUMNS} for e in (await db.execute(aq)).scalars()]
    return AUDIT_COLUMNS, rows


def export_response(
    slug: str, kind: str, fmt: ExportFormat, columns: list[str], rows: list[dict[str, Any]]
) -> Response:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    render: Callable[[], str] = (
        (lambda: to_csv(columns, rows)) if fmt == "csv" else (lambda: to_json(rows))
    )
    media = "text/csv; charset=utf-8" if fmt == "csv" else "application/json"
    return Response(
        content=render(),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="hootpr-{slug}-{kind}-{stamp}.{fmt}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/orgs/{org_slug}/export/{kind}")
async def export(
    kind: ExportKind,
    ctx: OrgMember,
    db: Db,
    settings: SettingsDep,
    owner: PlatformOwner,
    format: ExportFormat = "csv",
    days: Days = 30,
) -> Response:
    if kind == "audit" and ctx.role != "admin":
        raise api_error(403, "forbidden", "Only admins can export audit logs")
    since = datetime.now(UTC) - timedelta(days=days)
    columns, rows = await export_rows(
        db, ctx.org.id, kind, since, settings.export_max_rows, internal=owner
    )
    audit(
        db,
        ctx.org.id,
        "data.exported",
        actor=ctx.user,
        target_type="export",
        target_id=kind,
        details={"format": format, "days": days, "rows": len(rows)},
    )
    await db.commit()
    return export_response(ctx.org.slug, kind, format, columns, rows)
