"""Change Stack workspace API (spec §10.5).

Reads (diff, file contents) use the bot installation; submitting a review and merging use the
signed-in user's own OAuth token so the provider records and authorizes the human.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.analytics import schemas as A
from app.analytics.audit import audit
from app.api.orgs import reauth_error
from app.auth.provider_clients import ReauthRequired
from app.billing.ledger import CreditLedger, InsufficientCredits
from app.billing.pricing import fmt_credits, whole
from app.billing.rate_limit import Limited, RateLimiter
from app.change_stack.chat import CS_CHAT_REF_TYPE
from app.change_stack.workspace import (
    finding_out,
    group_files,
    language_for,
    pick_snapshot,
    relevant_findings,
    snapshots,
    task_like,
)
from app.crypto import Crypto
from app.deps import Db, OrgContext, OrgMember, SettingsDep, Tokens, get_queue
from app.errors import api_error
from app.kv import RedisKV
from app.logging import get_logger
from app.models import (
    ChangeStackMessage,
    Finding,
    Identity,
    PullRequest,
    Repository,
    Review,
    ReviewTask,
    User,
)
from app.platforms.base import FileDiff, GitPlatform, PlatformError, ReviewEvent
from app.platforms.factory import NotInstalled, close_platform, make_platform_factory, repo_ref
from app.platforms.user import user_platform
from app.platforms.workspace import MergeResult, UserReviewComment
from app.settings import Settings

router = APIRouter()
log = get_logger(__name__)
MAX_FILE_BYTES = 1_000_000
CHAT_TASK = "change_stack.chat"
LIST_LIMIT = 100


def pull_out(pr: PullRequest, repo: Repository) -> A.CsPull:
    return A.CsPull(
        id=str(pr.id),
        repo_id=str(repo.id),
        repo_full_name=repo.full_name,
        provider=repo.provider,
        number=pr.number,
        title=pr.title,
        url=pr.url,
        author_username=pr.author_username,
        state=pr.state,
        is_draft=pr.is_draft,
        base_ref=pr.base_ref,
        head_ref=pr.head_ref,
        head_sha=pr.head_sha,
        last_reviewed_sha=pr.last_reviewed_sha,
        updated_at=pr.updated_at,
    )


async def _pull(db: AsyncSession, ctx: OrgContext, pr_id: UUID) -> tuple[PullRequest, Repository]:
    row = (
        await db.execute(
            select(PullRequest, Repository)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .where(PullRequest.id == pr_id, Repository.org_id == ctx.org.id)
        )
    ).first()
    if row is None:
        raise api_error(404, "not_found", "Pull request not found")
    return row[0], row[1]


async def _bot_call[T](
    request: Request, db: AsyncSession, repo: Repository, fn: Callable[[GitPlatform], T]
) -> T:
    settings = cast(Settings, request.app.state.settings)
    factory = make_platform_factory(
        settings, RedisKV(request.app.state.sync_redis), cast(Crypto, request.app.state.crypto)
    )
    try:
        platform = await db.run_sync(lambda s: factory(s, repo))
    except NotInstalled as exc:
        raise api_error(409, "not_installed", "HootPR is not installed on this repository") from exc

    def run() -> T:
        try:
            return fn(platform)
        finally:
            close_platform(platform)

    try:
        return await run_in_threadpool(run)
    except PlatformError as exc:
        log.warning("cs_platform_error", status=exc.status_code, error=exc.message[:200])
        raise api_error(502, "provider_error", "The git provider request failed") from exc


# --- list & workspace -----------------------------------------------------------------------


@router.get("/api/orgs/{org_slug}/change-stack", response_model=A.CsPullList)
async def list_pulls(
    ctx: OrgMember, db: Db, state: str | None = "open", repo_id: UUID | None = None
) -> A.CsPullList:
    q = (
        select(PullRequest, Repository)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .where(Repository.org_id == ctx.org.id)
    )
    if state in ("open", "closed", "merged"):
        q = q.where(PullRequest.state == state)
    if repo_id is not None:
        q = q.where(Repository.id == repo_id)
    rows = (await db.execute(q.order_by(PullRequest.updated_at.desc()).limit(LIST_LIMIT))).all()
    return A.CsPullList(pulls=[pull_out(pr, repo) for pr, repo in rows])


async def _identity(db: AsyncSession, user_id: UUID, provider: str) -> Identity | None:
    return (
        await db.execute(
            select(Identity)
            .where(Identity.user_id == user_id, Identity.provider == provider)
            .order_by(Identity.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


def viewer(ident: Identity | None, pr: PullRequest, provider: str) -> A.CsViewer:
    has_token = ident is not None and bool(ident.access_token_enc)
    reason: str | None = None
    if ident is None:
        reason = f"Link your {provider} account to submit reviews or merge from Change Stack."
    elif not has_token:
        reason = f"Sign in with {provider} again to act on this pull request."
    elif pr.state != "open":
        reason = f"This pull request is {pr.state}."
    ok = has_token and pr.state == "open"
    return A.CsViewer(
        username=ident.username if ident else None,
        has_token=has_token,
        can_submit=ok,
        can_merge=ok and not pr.is_draft,
        reason=reason
        if not ok
        else ("Draft pull requests cannot be merged." if pr.is_draft else None),
    )


@router.get("/api/orgs/{org_slug}/change-stack/{pr_id}", response_model=A.CsWorkspace)
async def workspace(
    pr_id: UUID, request: Request, ctx: OrgMember, db: Db, sha: str | None = None
) -> A.CsWorkspace:
    pr, repo = await _pull(db, ctx, pr_id)
    reviews = list((await db.execute(select(Review).where(Review.pr_id == pr.id))).scalars())
    snaps = snapshots(reviews, pr.head_sha)
    snap = pick_snapshot(snaps, sha)
    if sha and snap is None:
        raise api_error(404, "not_found", "No reviewed snapshot for that SHA")
    snap_review = next((r for r in reviews if snap and str(r.id) == snap.review_id), None)
    rows = (
        await db.execute(
            select(Finding, Review)
            .join(Review, Review.id == Finding.review_id)
            .where(Review.pr_id == pr.id)
        )
    ).all()
    findings = relevant_findings(
        [(f, r) for f, r in rows], snap_review.created_at if snap_review else None
    )
    tasks = []
    if snap_review is not None:
        tasks = [
            task_like(t)
            for t in (
                await db.execute(select(ReviewTask).where(ReviewTask.review_id == snap_review.id))
            ).scalars()
        ]
    head = snap.head_sha if snap else pr.head_sha
    is_current = head == pr.head_sha
    base_ref = pr.base_ref or repo.default_branch
    number = pr.number
    ref = repo_ref(repo)
    diff: list[FileDiff] = []
    diff_error: str | None = None
    try:
        diff = await _bot_call(
            request,
            db,
            repo,
            lambda p: (
                p.get_diff(ref, number) if is_current else p.get_diff(ref, number, base_ref, head)
            ),
        )
    except Exception as exc:  # the workspace still shows snapshots and findings
        detail = getattr(exc, "detail", None)
        diff_error = (
            str(detail.get("message")) if isinstance(detail, dict) else "Could not load the diff"
        )
    ident = await _identity(db, ctx.user.id, repo.provider)
    return A.CsWorkspace(
        pull=pull_out(pr, repo),
        snapshots=snaps,
        snapshot=snap,
        stale=bool(snap and snap.stale),
        groups=group_files(diff, tasks, findings),
        findings=[finding_out(f) for f in findings],
        viewer=viewer(ident, pr, repo.provider),
        diff_error=diff_error,
    )


@router.get("/api/orgs/{org_slug}/change-stack/{pr_id}/file", response_model=A.CsFileContents)
async def file_contents(
    pr_id: UUID,
    request: Request,
    ctx: OrgMember,
    db: Db,
    path: Annotated[str, Query(min_length=1, max_length=1024)],
    sha: str | None = None,
    old_path: str | None = None,
    status: str | None = None,
) -> A.CsFileContents:
    pr, repo = await _pull(db, ctx, pr_id)
    head = sha or pr.head_sha
    base = pr.base_sha or pr.base_ref
    ref = repo_ref(repo)

    def load(p: GitPlatform) -> tuple[str, str]:
        original = "" if status == "added" else (p.get_file(ref, old_path or path, base) or "")
        modified = "" if status == "removed" else (p.get_file(ref, path, head) or "")
        return original, modified

    original, modified = await _bot_call(request, db, repo, load)
    truncated = len(original) > MAX_FILE_BYTES or len(modified) > MAX_FILE_BYTES
    return A.CsFileContents(
        path=path,
        original=original[:MAX_FILE_BYTES],
        modified=modified[:MAX_FILE_BYTES],
        language=language_for(path),
        truncated=truncated,
    )


# --- pinned chat --------------------------------------------------------------------------


def _msg(m: ChangeStackMessage, author: str | None) -> A.CsMessage:
    return A.CsMessage(
        id=str(m.id),
        role="assistant" if m.role == "assistant" else "user",
        body=m.body,
        author=author,
        path=m.path,
        line=m.line,
        head_sha=m.head_sha,
        status=m.status,
        credits_charged=whole(m.credits_charged),
        created_at=m.created_at,
    )


@router.get("/api/orgs/{org_slug}/change-stack/{pr_id}/chat", response_model=A.CsMessageList)
async def chat_messages(pr_id: UUID, ctx: OrgMember, db: Db) -> A.CsMessageList:
    pr, _ = await _pull(db, ctx, pr_id)
    rows = (
        await db.execute(
            select(ChangeStackMessage, User.display_name)
            .outerjoin(User, User.id == ChangeStackMessage.user_id)
            .where(ChangeStackMessage.pr_id == pr.id, ChangeStackMessage.org_id == ctx.org.id)
            .order_by(ChangeStackMessage.created_at, ChangeStackMessage.role.desc())
            .limit(200)
        )
    ).all()
    return A.CsMessageList(
        messages=[_msg(m, name if m.role == "user" else "HootPR") for m, name in rows]
    )


@router.post(
    "/api/orgs/{org_slug}/change-stack/{pr_id}/chat",
    response_model=A.CsMessageList,
    status_code=202,
)
async def ask(
    pr_id: UUID,
    body: A.CsMessageIn,
    request: Request,
    ctx: OrgMember,
    db: Db,
    settings: SettingsDep,
) -> A.CsMessageList:
    pr, _repo = await _pull(db, ctx, pr_id)
    limiter = RateLimiter.from_settings(request.app.state.sync_redis, settings)
    limited = await run_in_threadpool(limiter.check_and_consume, ctx.org.id, "chat")
    if isinstance(limited, Limited):
        raise api_error(
            429,
            "rate_limited",
            f"Chat limit reached; try again in {max(1, limited.retry_after_s // 60)} min",
            retry_after_s=limited.retry_after_s,
        )
    q = ChangeStackMessage(
        org_id=ctx.org.id,
        pr_id=pr.id,
        user_id=ctx.user.id,
        role="user",
        body=body.body.strip(),
        head_sha=body.head_sha or pr.head_sha,
        path=body.path,
        line=body.line,
        status="completed",
    )
    db.add(q)
    await db.flush()
    a = ChangeStackMessage(
        org_id=ctx.org.id,
        pr_id=pr.id,
        role="assistant",
        body="",
        head_sha=q.head_sha,
        path=q.path,
        line=q.line,
        status="queued",
        question_id=q.id,
    )
    db.add(a)
    await db.flush()
    org_id, answer_id = ctx.org.id, a.id
    amount, minimum = settings.chat_hold_max, settings.chat_min_charge

    def _reserve(s: Session) -> object:
        return CreditLedger().reserve_up_to(s, org_id, amount, minimum, CS_CHAT_REF_TYPE, answer_id)

    hold = await db.run_sync(_reserve)
    if isinstance(hold, InsufficientCredits):
        await db.rollback()
        raise api_error(
            402,
            "no_credits",
            f"Chat needs at least {fmt_credits(minimum)} credits; the balance is "
            f"{fmt_credits(hold.balance)}",
        )
    await db.commit()
    get_queue(request).enqueue(CHAT_TASK, str(answer_id))
    await db.refresh(q)
    await db.refresh(a)
    return A.CsMessageList(messages=[_msg(q, ctx.user.display_name), _msg(a, "HootPR")])


# --- submit review / merge (user's own token) ----------------------------------------------


async def _as_user[T](
    request: Request,
    db: AsyncSession,
    tokens: Tokens,
    ctx: OrgContext,
    repo: Repository,
    fn: Callable[[GitPlatform], T],
) -> T:
    settings = cast(Settings, request.app.state.settings)
    ident = await _identity(db, ctx.user.id, repo.provider)
    if ident is None or not ident.access_token_enc:
        raise api_error(
            403, "no_provider_token", f"Sign in with {repo.provider} to act on this pull request"
        )

    async def call(token: str) -> T:
        def run() -> T:
            p = user_platform(repo.provider, token, settings)
            try:
                return fn(p)
            except PlatformError as exc:
                if exc.status_code == 401:
                    raise ReauthRequired(exc.message) from exc
                raise
            finally:
                close_platform(p)

        return await run_in_threadpool(run)

    try:
        return await tokens.call(ident, call)
    except ReauthRequired as exc:
        raise reauth_error() from exc
    except PlatformError as exc:
        if exc.status_code in (403, 404):
            raise api_error(
                403, "provider_forbidden", "Your account cannot do this on the pull request"
            ) from exc
        if exc.status_code == 422:
            raise api_error(422, "provider_rejected", exc.message[:300]) from exc
        raise api_error(502, "provider_error", "The git provider request failed") from exc


@router.post(
    "/api/orgs/{org_slug}/change-stack/{pr_id}/review",
    response_model=A.CsReviewOut,
    status_code=201,
)
async def submit_review(
    pr_id: UUID, body: A.CsReviewIn, request: Request, ctx: OrgMember, db: Db, tokens: Tokens
) -> A.CsReviewOut:
    pr, repo = await _pull(db, ctx, pr_id)
    if pr.state != "open":
        raise api_error(409, "pr_not_open", "The pull request is not open")
    if body.event != "APPROVE" and not body.body.strip() and not body.comments:
        raise api_error(422, "empty_review", "Add a summary or at least one comment")
    ref, number = repo_ref(repo), pr.number
    comments = [
        UserReviewComment(c.path, c.line, c.body, c.start_line, c.side) for c in body.comments
    ]
    event: ReviewEvent = body.event
    review_ref = await _as_user(
        request,
        db,
        tokens,
        ctx,
        repo,
        lambda p: p.submit_review(ref, number, body.head_sha, event, body.body, comments),
    )
    audit(
        db,
        ctx.org.id,
        "change_stack.review_submitted",
        actor=ctx.user,
        target_type="pull_request",
        target_id=pr.id,
        details={
            "repo": repo.full_name,
            "number": number,
            "event": body.event,
            "comments": len(comments),
        },
    )
    await db.commit()
    return A.CsReviewOut(review_ref=review_ref, event=body.event)


@router.post("/api/orgs/{org_slug}/change-stack/{pr_id}/merge", response_model=A.CsMergeOut)
async def merge(
    pr_id: UUID, body: A.CsMergeIn, request: Request, ctx: OrgMember, db: Db, tokens: Tokens
) -> A.CsMergeOut:
    pr, repo = await _pull(db, ctx, pr_id)
    if pr.state != "open":
        raise api_error(409, "pr_not_open", "The pull request is not open")
    ref, number = repo_ref(repo), pr.number
    res: MergeResult = await _as_user(
        request,
        db,
        tokens,
        ctx,
        repo,
        lambda p: p.merge_pull_request(
            ref, number, method=body.method, sha=body.head_sha, commit_title=body.commit_title
        ),
    )
    if res.merged:
        pr.state = "merged"
    audit(
        db,
        ctx.org.id,
        "change_stack.merge",
        actor=ctx.user,
        target_type="pull_request",
        target_id=pr.id,
        details={
            "repo": repo.full_name,
            "number": number,
            "method": body.method,
            "merged": res.merged,
        },
    )
    await db.commit()
    return A.CsMergeOut(merged=res.merged, sha=res.sha, message=res.message)
