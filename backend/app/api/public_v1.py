"""Public REST API ``/api/public/v1/*`` authenticated with per-org API keys (spec §10.5).

API keys never see internal LLM data (tokens / cost / models): only HootPR credits.

Cookie-less (CSRF-exempt): ``Authorization: Bearer hpr_…`` or ``X-API-Key: hpr_…``. Each key is
limited to ``PUBLIC_API_RATE_PER_MINUTE`` requests per minute.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.analytics import schemas as A
from app.analytics.api_keys import extract_key, hash_key, looks_like_key
from app.api import schemas as S
from app.api.analytics import org_metrics, org_usage
from app.api.learnings import _out as learning_out
from app.api.reports import create_custom_run, get_run, list_runs, run_detail, run_summary
from app.api.reviews import _finding, _joined, _summary
from app.auth.platform import strip_internal
from app.billing.pricing import whole
from app.deps import Db, SettingsDep, get_queue, get_redis
from app.errors import api_error
from app.models import ApiKey, Finding, Learning, Organization, Repository, Review

router = APIRouter(prefix="/api/public/v1", tags=["public"])
LAST_USED_EVERY = timedelta(minutes=1)


@dataclass
class KeyContext:
    key: ApiKey
    org: Organization

    @property
    def label(self) -> str:
        return f"api_key:{self.key.prefix}"


async def api_key_context(
    request: Request,
    db: Db,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> KeyContext:
    secret = extract_key(authorization, x_api_key)
    if not looks_like_key(secret) or secret is None:
        raise api_error(401, "invalid_api_key", "Missing or invalid API key")
    row = (
        await db.execute(
            select(ApiKey, Organization)
            .join(Organization, Organization.id == ApiKey.org_id)
            .where(ApiKey.key_hash == hash_key(secret))
        )
    ).first()
    now = datetime.now(UTC)
    if row is None:
        raise api_error(401, "invalid_api_key", "Missing or invalid API key")
    key, org = row
    if key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= now):
        raise api_error(401, "invalid_api_key", "API key revoked or expired")
    if org.blocked:
        raise api_error(403, "org_blocked", "Organization is blocked")
    redis = get_redis(request)
    bucket = f"papi:{key.id}:{now:%Y%m%d%H%M}"
    n = int(await redis.incr(bucket))
    if n == 1:
        await redis.expire(bucket, 120)
    if n > settings.public_api_rate_per_minute:
        raise api_error(429, "rate_limited", "API key rate limit exceeded; retry in a minute")
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_EVERY:
        key.last_used_at = now
        await db.commit()
    return KeyContext(key=key, org=org)


Key = Annotated[KeyContext, Depends(api_key_context)]
Days = Annotated[int, Query(ge=1, le=365)]


@router.get("/org", response_model=A.PublicOrg)
async def org(k: Key) -> A.PublicOrg:
    return A.PublicOrg(
        id=str(k.org.id),
        slug=k.org.slug,
        name=k.org.name,
        provider=k.org.provider,
        credits_balance=whole(k.org.credits_balance),
    )


@router.get("/metrics", response_model=A.Metrics)
async def metrics(k: Key, db: Db, days: Days = 30, repo_id: UUID | None = None) -> A.Metrics:
    return strip_internal(await org_metrics(db, k.org, days, repo_id))


@router.get("/usage", response_model=A.Usage)
async def usage(k: Key, db: Db, days: Days = 30, repo_id: UUID | None = None) -> A.Usage:
    return strip_internal(await org_usage(db, k.org, days, repo_id))


@router.get("/reviews", response_model=S.ReviewList)
async def reviews(
    k: Key,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
    repo_id: UUID | None = None,
) -> S.ReviewList:
    q = _joined().where(Review.org_id == k.org.id)
    if before is not None:
        q = q.where(Review.created_at < before)
    if repo_id is not None:
        q = q.where(Repository.id == repo_id)
    rows = (await db.execute(q.order_by(Review.created_at.desc()).limit(limit))).all()
    items = [_summary(r, pr, repo) for r, pr, repo in rows]
    return strip_internal(
        S.ReviewList(
            reviews=items, next_before=items[-1].created_at if len(items) == limit else None
        )
    )


class PublicReviewDetail(S.ReviewSummary):
    head_sha: str
    base_sha: str | None
    findings: list[S.Finding]


@router.get("/reviews/{review_id}", response_model=PublicReviewDetail)
async def review(review_id: UUID, k: Key, db: Db) -> PublicReviewDetail:
    row = (
        await db.execute(_joined().where(Review.id == review_id, Review.org_id == k.org.id))
    ).first()
    if row is None:
        raise api_error(404, "not_found", "Review not found")
    r, pr, repo = row
    findings = (
        await db.execute(
            select(Finding)
            .where(Finding.review_id == r.id, Finding.posted.is_(True))
            .order_by(Finding.path, Finding.end_line)
        )
    ).scalars()
    return strip_internal(
        PublicReviewDetail(
            **_summary(r, pr, repo).model_dump(),
            head_sha=r.head_sha,
            base_sha=r.base_sha,
            findings=[_finding(f) for f in findings],
        )
    )


class PublicLearnings(BaseModel):
    learnings: list[S.Learning]


@router.get("/learnings", response_model=PublicLearnings)
async def learnings(
    k: Key, db: Db, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> PublicLearnings:
    rows = (
        await db.execute(
            select(Learning, Repository.full_name)
            .outerjoin(Repository, Repository.id == Learning.repo_id)
            .where(Learning.org_id == k.org.id)
            .order_by(Learning.created_at.desc())
            .limit(limit)
        )
    ).all()
    return PublicLearnings(learnings=[learning_out(row, name) for row, name in rows])


@router.get("/reports", response_model=A.ReportRunList)
async def reports(
    k: Key,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: datetime | None = None,
) -> A.ReportRunList:
    return await list_runs(db, k.org.id, limit, before)


@router.get("/reports/{run_id}", response_model=A.ReportRunDetail)
async def report(run_id: UUID, k: Key, db: Db) -> A.ReportRunDetail:
    return strip_internal(run_detail(await get_run(db, k.org.id, run_id)))


@router.post("/reports", response_model=A.ReportRunSummary, status_code=202)
async def create_report(
    body: A.CustomReportIn, request: Request, k: Key, db: Db, settings: SettingsDep
) -> A.ReportRunSummary:
    run = await create_custom_run(
        db, get_redis(request), get_queue(request), settings, k.org, body, None, k.label
    )
    return run_summary(run)
