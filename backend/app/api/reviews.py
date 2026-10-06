"""Reviews list + detail with trace (dashboard Reviews page, spec §11.4)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import ValidationError
from sqlalchemy import Select, case, select

from app.api import schemas as S
from app.api.receipts import REVIEW, build_receipt, ledger_entries
from app.auth.platform import for_viewer
from app.billing.pricing import CREDIT
from app.deps import Db, OrgMember, PlatformOwner, SettingsDep
from app.errors import api_error
from app.models import (
    AgentStep,
    Finding,
    LlmCall,
    PullRequest,
    Repository,
    Review,
    ReviewTask,
    ToolRun,
)

router = APIRouter()
MICRO = Decimal("0.000001")
# Contract C4: findings ordered by (posted desc, severity rank, path, end_line).
SEVERITY_ORDER = case(
    {"critical": 0, "major": 1, "minor": 2, "nitpick": 3}, value=Finding.severity, else_=4
)
JUDGE_VERDICTS = frozenset({"keep", "drop", "merge"})
TASK_STATUSES = frozenset({"pending", "running", "done", "skipped", "failed"})


def _usd(value: Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(value).quantize(MICRO)


def _summary(r: Review, pr: PullRequest, repo: Repository) -> S.ReviewSummary:
    return S.ReviewSummary(
        id=str(r.id),
        repo_full_name=repo.full_name,
        pr_number=pr.number,
        pr_title=pr.title,
        pr_url=pr.url,
        trigger=cast(S.ReviewTriggerT, r.trigger),
        status=cast(S.ReviewStatus, r.status),
        skip_reason=r.skip_reason,
        credits_charged=Decimal(r.credits_charged).quantize(CREDIT),
        findings_posted=r.findings_posted,
        files_considered=r.files_considered,
        input_tokens=r.input_tokens,
        output_tokens=r.output_tokens,
        cost_usd=_usd(r.cost_usd),
        created_at=r.created_at,
        finished_at=r.finished_at,
    )


def _joined() -> Select[Review, PullRequest, Repository]:
    return (
        select(Review, PullRequest, Repository)
        .join(PullRequest, PullRequest.id == Review.pr_id)
        .join(Repository, Repository.id == PullRequest.repo_id)
    )


@router.get("/api/orgs/{org_slug}/reviews", response_model=S.ReviewList)
async def list_reviews(
    ctx: OrgMember,
    db: Db,
    owner: PlatformOwner,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
    repo_id: UUID | None = None,
) -> S.ReviewList:
    q = _joined().where(Review.org_id == ctx.org.id)
    if before is not None:
        q = q.where(Review.created_at < before)
    if repo_id is not None:
        q = q.where(Repository.id == repo_id)
    q = q.order_by(Review.created_at.desc(), Review.id.desc()).limit(limit)
    rows = (await db.execute(q)).all()
    items = [_summary(r, pr, repo) for r, pr, repo in rows]
    next_before = items[-1].created_at if len(items) == limit else None
    return for_viewer(S.ReviewList(reviews=items, next_before=next_before), owner)


def _llm_call(c: LlmCall) -> S.LlmCall:
    return S.LlmCall(
        id=str(c.id),
        task_id=str(c.task_id) if c.task_id else None,
        role=c.role,
        model=c.model,
        provider_host=c.provider_host,
        input_tokens=c.input_tokens,
        cached_tokens=c.cached_tokens,
        output_tokens=c.output_tokens,
        cost_usd=_usd(c.cost_usd),
        latency_ms=c.latency_ms,
        status=c.status,
        error=c.error,
        structured_mode=c.structured_mode,
        created_at=c.created_at,
        stage=c.stage,
        credits=None if c.credits is None else Decimal(c.credits).quantize(MICRO),
    )


def _stage(raw: Any) -> S.ReviewStage | None:
    if not isinstance(raw, dict):
        return None
    try:
        return S.ReviewStage.model_validate({"detail": None, **raw})
    except ValidationError:
        return None  # a malformed row never breaks the page


def _finding(f: Finding) -> S.Finding:
    verdict = f.judge_verdict if f.judge_verdict in JUDGE_VERDICTS else None
    return S.Finding(
        id=str(f.id),
        path=f.path,
        start_line=f.start_line,
        end_line=f.end_line,
        side=f.side,
        severity=f.severity,
        category=f.category,
        title=f.title,
        body=f.body,
        suggestion=f.suggestion,
        posted=f.posted,
        status=f.status,
        source=f.source,
        confidence=f.confidence,
        task_id=str(f.task_id) if f.task_id else None,
        judge_verdict=cast(S.JudgeVerdictT | None, verdict),
        judge_reason=f.judge_reason,
        fingerprint=f.fingerprint,
        evidence=[str(e) for e in (f.evidence or [])],
    )


def _task(t: ReviewTask) -> S.ReviewTask:
    status = t.status if t.status in TASK_STATUSES else "failed"
    return S.ReviewTask(
        id=str(t.id),
        ordinal=t.ordinal,
        title=t.title,
        rationale=t.rationale,
        files=list(t.files or []),
        focus=list(t.focus or []),
        status=cast(S.TaskStatus, status),
        summary=t.summary,
    )


@router.get("/api/orgs/{org_slug}/reviews/{review_id}", response_model=S.ReviewDetail)
async def review_detail(
    review_id: UUID, ctx: OrgMember, db: Db, owner: PlatformOwner, settings: SettingsDep
) -> S.ReviewDetail:
    q = _joined().where(Review.id == review_id, Review.org_id == ctx.org.id)
    row = (await db.execute(q)).first()
    if row is None:
        raise api_error(404, "not_found", "Review not found")
    r, pr, repo = row
    findings = (
        await db.execute(
            select(Finding)
            .where(Finding.review_id == r.id)
            .order_by(
                Finding.posted.desc(), SEVERITY_ORDER, Finding.path, Finding.end_line, Finding.id
            )
        )
    ).scalars()
    tasks = (
        await db.execute(
            select(ReviewTask).where(ReviewTask.review_id == r.id).order_by(ReviewTask.ordinal)
        )
    ).scalars()
    calls = list(
        (
            await db.execute(
                select(LlmCall)
                .where(LlmCall.review_id == r.id)
                .order_by(LlmCall.created_at, LlmCall.id)
            )
        ).scalars()
    )
    entries = await ledger_entries(db, ctx.org.id, REVIEW, r.id)
    steps = (
        await db.execute(
            select(AgentStep)
            .where(AgentStep.review_id == r.id)
            .order_by(AgentStep.step_no, AgentStep.created_at, AgentStep.id)
        )
    ).scalars()
    tools = (
        await db.execute(
            select(ToolRun).where(ToolRun.review_id == r.id).order_by(ToolRun.created_at)
        )
    ).scalars()
    detail = S.ReviewDetail(
        **_summary(r, pr, repo).model_dump(),
        base_sha=r.base_sha,
        head_sha=r.head_sha,
        error=r.error,
        degraded=r.degraded or {},
        files_reviewed=r.files_reviewed,
        findings=[_finding(f) for f in findings],
        trace=S.Trace(
            stages=[s for s in (_stage(x) for x in r.stages or []) if s is not None],
            tasks=[_task(t) for t in tasks],
            llm_calls=[_llm_call(c) for c in calls],
            agent_steps=[
                S.AgentStep(
                    id=str(a.id),
                    task_id=str(a.task_id) if a.task_id else None,
                    step_no=a.step_no,
                    kind=a.kind,
                    tool_name=a.tool_name,
                    args=dict(a.args or {}),
                    output_excerpt=a.output_excerpt,
                    duration_ms=a.duration_ms,
                    created_at=a.created_at,
                )
                for a in steps
            ],
            tool_runs=[
                S.ToolRun(
                    id=str(t.id),
                    tool=t.tool,
                    status=t.status,
                    duration_ms=t.duration_ms,
                    findings_count=t.findings_count,
                    stderr_excerpt=t.stderr_excerpt,
                )
                for t in tools
            ],
        ),
        receipt=build_receipt(
            entries,
            calls,
            settings.review_min_charge,
            budget_reached=(r.degraded or {}).get("credit_budget") == "reached",
        ),
    )
    return for_viewer(detail, owner)


@router.get(
    "/api/orgs/{org_slug}/reviews/{review_id}/llm-calls/{call_id}",
    response_model=S.LlmCallDetail,
)
async def llm_call_detail(
    review_id: UUID, call_id: UUID, ctx: OrgMember, db: Db, owner: PlatformOwner
) -> S.LlmCallDetail:
    if not owner:  # model / tokens / cost / prompts are internal to the platform
        raise api_error(404, "not_found", "LLM call not found")
    c = (
        await db.execute(
            select(LlmCall)
            .join(Review, Review.id == LlmCall.review_id)
            .where(LlmCall.id == call_id, Review.id == review_id, Review.org_id == ctx.org.id)
        )
    ).scalar_one_or_none()
    if c is None:
        raise api_error(404, "not_found", "LLM call not found")
    return S.LlmCallDetail(
        **_llm_call(c).model_dump(),
        request_excerpt=c.request_excerpt,
        response_excerpt=c.response_excerpt,
    )
