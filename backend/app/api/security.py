"""Security dashboard API (spec §10.3): attack surface maps and security architecture reviews."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.billing.pricing import fmt_credits
from app.deps import Db, OrgMember, SettingsDep, get_queue
from app.errors import api_error
from app.models import Organization, Repository, SecurityScan
from app.models.base import utcnow
from app.security.store import ACTIVE, TASK

router = APIRouter()
ScanKind = Literal["surface_map", "security_review"]
ScanStatus = Literal["queued", "running", "completed", "failed", "no_credits"]
STALE_AFTER = timedelta(minutes=60)
HISTORY = 10


class ScanSummary(BaseModel):
    id: str
    repo_id: str
    kind: ScanKind
    status: ScanStatus
    trigger: str
    requested_by: str
    branch: str
    commit_sha: str
    summary: str
    error: str | None
    credits_charged: Decimal
    overall_risk: str | None
    stats: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None


class ScanDetail(ScanSummary):
    surface: dict[str, Any] | None
    report: dict[str, Any] | None


class RepoSecurity(BaseModel):
    repo_id: str
    full_name: str
    provider: str
    default_branch: str
    latest_surface: ScanSummary | None
    latest_review: ScanSummary | None
    active: list[ScanSummary]
    history: list[ScanSummary]


class SecurityOverview(BaseModel):
    credits_security_review: Decimal
    balance: Decimal
    can_run_review: bool
    repos: list[RepoSecurity]


class StartScanRequest(BaseModel):
    kind: ScanKind


def _summary(s: SecurityScan) -> ScanSummary:
    result = s.result or {}
    surface = result.get("surface") if isinstance(result.get("surface"), dict) else {}
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    status: Any = s.status
    if s.status in ACTIVE and s.updated_at < utcnow() - STALE_AFTER:
        status = "failed"
    return ScanSummary(
        id=str(s.id),
        repo_id=str(s.repo_id),
        kind=s.kind,
        status=status,
        trigger=s.trigger,
        requested_by=s.requested_by,
        branch=s.branch,
        commit_sha=s.commit_sha,
        summary=s.summary,
        error=s.error,
        credits_charged=Decimal(s.credits_charged),
        overall_risk=(report or {}).get("overall_risk"),
        stats=(surface or {}).get("stats") or {},
        created_at=s.created_at,
        finished_at=s.finished_at,
    )


def _detail(s: SecurityScan) -> ScanDetail:
    result = s.result or {}
    surface = result.get("surface")
    report = result.get("report")
    return ScanDetail(
        **_summary(s).model_dump(),
        surface=surface if isinstance(surface, dict) else None,
        report=report if isinstance(report, dict) else None,
    )


def _fresh_active(s: SecurityScan) -> bool:
    return s.status in ACTIVE and s.updated_at >= utcnow() - STALE_AFTER


async def _repo(db: Db, org: Organization, repo_id: UUID) -> Repository:
    repo = (
        await db.execute(
            select(Repository).where(Repository.id == repo_id, Repository.org_id == org.id)
        )
    ).scalar_one_or_none()
    if repo is None:
        raise api_error(404, "not_found", "Repository not found")
    return repo


@router.get("/api/orgs/{org_slug}/security", response_model=SecurityOverview)
async def overview(ctx: OrgMember, db: Db, settings: SettingsDep) -> SecurityOverview:
    repos = (
        (
            await db.execute(
                select(Repository)
                .where(Repository.org_id == ctx.org.id, Repository.installation_id.is_not(None))
                .order_by(Repository.full_name)
            )
        )
        .scalars()
        .all()
    )
    out: list[RepoSecurity] = []
    for r in repos:
        scans = (
            (
                await db.execute(
                    select(SecurityScan)
                    .where(SecurityScan.repo_id == r.id)
                    .order_by(SecurityScan.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        surface = next(
            (x for x in scans if x.status == "completed" and (x.result or {}).get("surface")),
            None,
        )
        review = next((x for x in scans if x.kind == "security_review"), None)
        out.append(
            RepoSecurity(
                repo_id=str(r.id),
                full_name=r.full_name,
                provider=r.provider,
                default_branch=r.default_branch,
                latest_surface=_summary(surface) if surface else None,
                latest_review=_summary(review) if review else None,
                active=[_summary(x) for x in scans if _fresh_active(x)],
                history=[_summary(x) for x in scans[:HISTORY]],
            )
        )
    return SecurityOverview(
        # The most a (metered) security review can charge: its hold.
        credits_security_review=settings.security_hold_max,
        balance=Decimal(ctx.org.credits_balance),
        can_run_review=ctx.role == "admin",
        repos=out,
    )


@router.get("/api/orgs/{org_slug}/security/scans/{scan_id}", response_model=ScanDetail)
async def scan_detail(scan_id: UUID, ctx: OrgMember, db: Db) -> ScanDetail:
    scan = (
        await db.execute(
            select(SecurityScan).where(
                SecurityScan.id == scan_id, SecurityScan.org_id == ctx.org.id
            )
        )
    ).scalar_one_or_none()
    if scan is None:
        raise api_error(404, "not_found", "Scan not found")
    return _detail(scan)


@router.post(
    "/api/orgs/{org_slug}/repos/{repo_id}/security/scans",
    response_model=ScanSummary,
    status_code=202,
)
async def start_scan(
    repo_id: UUID,
    body: StartScanRequest,
    request: Request,
    ctx: OrgMember,
    db: Db,
    settings: SettingsDep,
) -> ScanSummary:
    """Surface maps are free (any member); security reviews cost credits (admins only)."""
    repo = await _repo(db, ctx.org, repo_id)
    if body.kind == "security_review":
        if ctx.role != "admin":
            raise api_error(403, "forbidden", "Only organization admins can run security reviews")
        if Decimal(ctx.org.credits_balance) < settings.security_min_charge:
            raise api_error(
                402,
                "insufficient_credits",
                f"A security review needs at least {fmt_credits(settings.security_min_charge)} "
                "credits to start. Top up on the billing page.",
            )
    existing = (
        (
            await db.execute(
                select(SecurityScan)
                .where(
                    SecurityScan.repo_id == repo.id,
                    SecurityScan.kind == body.kind,
                    SecurityScan.status.in_(ACTIVE),
                )
                .order_by(SecurityScan.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    fresh = next((x for x in existing if _fresh_active(x)), None)
    if fresh is not None:
        return _summary(fresh)
    user = ctx.user
    scan = SecurityScan(
        org_id=ctx.org.id,
        repo_id=repo.id,
        kind=body.kind,
        status="queued",
        trigger="dashboard",
        requested_by=(user.display_name or user.email or "")[:255],
        branch=repo.default_branch or "main",
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    try:
        get_queue(request).enqueue(TASK, str(scan.id))
    except Exception as exc:
        scan.status, scan.error = "failed", "Could not queue the job."
        await db.commit()
        raise api_error(503, "queue_unavailable", "Could not start the scan, try again") from exc
    return _summary(scan)
