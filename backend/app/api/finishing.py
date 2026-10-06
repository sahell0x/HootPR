"""Finishing-touch jobs for the dashboard (Phase 4): listed per org, or per review's PR."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.billing.pricing import whole
from app.deps import Db, OrgMember
from app.errors import api_error
from app.models import FinishingJob, PullRequest, Repository, Review

router = APIRouter()


class FinishingJobOut(BaseModel):
    id: str
    repo_full_name: str
    pr_number: int
    kind: str
    recipe_name: str | None
    trigger: str
    delivery: str
    status: str
    requested_by: str
    head_sha: str
    result_sha: str | None
    result_pr_number: int | None
    result_url: str | None
    verification: str
    files_changed: int
    summary: str | None
    error: str | None
    credits_charged: Decimal
    created_at: datetime
    finished_at: datetime | None


class FinishingJobList(BaseModel):
    jobs: list[FinishingJobOut]


def _out(j: FinishingJob, pr: PullRequest, repo: Repository) -> FinishingJobOut:
    return FinishingJobOut(
        id=str(j.id),
        repo_full_name=repo.full_name,
        pr_number=pr.number,
        kind=j.kind,
        recipe_name=j.recipe_name,
        trigger=j.trigger,
        delivery=j.delivery,
        status=j.status,
        requested_by=j.requested_by,
        head_sha=j.head_sha,
        result_sha=j.result_sha,
        result_pr_number=j.result_pr_number,
        result_url=j.result_url,
        verification=j.verification,
        files_changed=j.files_changed,
        summary=j.summary,
        # internal errors stay in the logs; only user-facing ones are stored short
        error=(j.error or "")[:300] or None,
        credits_charged=whole(j.credits_charged),
        created_at=j.created_at,
        finished_at=j.finished_at,
    )


@router.get("/api/orgs/{org_slug}/finishing-jobs", response_model=FinishingJobList)
async def list_finishing_jobs(
    ctx: OrgMember,
    db: Db,
    review_id: UUID | None = None,
    pr_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> FinishingJobList:
    """Newest first. ``review_id`` lists the jobs of that review's pull request."""
    if review_id is not None:
        review = await db.get(Review, review_id)
        if review is None or review.org_id != ctx.org.id:
            raise api_error(404, "not_found", "Review not found")
        pr_id = review.pr_id
    q = (
        select(FinishingJob, PullRequest, Repository)
        .join(PullRequest, PullRequest.id == FinishingJob.pr_id)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .where(FinishingJob.org_id == ctx.org.id)
    )
    if pr_id is not None:
        q = q.where(FinishingJob.pr_id == pr_id)
    q = q.order_by(FinishingJob.created_at.desc(), FinishingJob.id.desc()).limit(limit)
    rows = (await db.execute(q)).all()
    return FinishingJobList(jobs=[_out(j, pr, repo) for j, pr, repo in rows])
