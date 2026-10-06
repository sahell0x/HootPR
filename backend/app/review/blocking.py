"""``reviews.request_changes_workflow`` (spec §7.7, phase-3 R18).

Open blocking findings = posted HootPR findings of severity critical/major whose platform thread
is not resolved. While any are open the PR carries a failing "Changes requested" check; when the
last one is resolved the check turns green and HootPR approves the PR once per transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.loader import load_effective_config
from app.config.schema import HootPRConfig
from app.logging import get_logger
from app.models import Finding, Organization, PullRequest, Repository, Review
from app.platforms.base import CheckState, GitPlatform, RepoRef
from app.platforms.factory import close_platform, repo_ref
from app.worker.context import WorkerContext

log = get_logger(__name__)
BLOCKING_SEVERITIES = ("critical", "major")
APPROVE_BODY = "✅ All blocking HootPR comments are resolved. Approving."


@dataclass(frozen=True)
class BlockingState:
    open_blocking: int
    newly_resolved: int


def sync_resolution(
    s: Session, platform: GitPlatform, ref: RepoRef, pr: PullRequest, *, read_platform: bool = True
) -> BlockingState:
    """Mirror the platform's thread resolution onto this PR's posted findings.

    ``read_platform=False`` trusts the finding rows as they are: used right after HootPR resolved
    the threads itself (``resolve``/``approve``), when a platform read may still be stale."""
    state: dict[str, bool] = {}
    comments = platform.list_comments(ref, pr.number) if read_platform else []
    for c in comments:
        if c.thread_ref and c.resolved is not None:
            state[c.thread_ref] = state.get(c.thread_ref, False) or c.resolved
    rows = (
        s.execute(
            select(Finding)
            .join(Review, Review.id == Finding.review_id)
            .where(
                Review.pr_id == pr.id,
                Finding.posted.is_(True),
                Finding.provider_comment_id.is_not(None),
                Finding.status.in_(("open", "resolved")),
            )
        )
        .scalars()
        .all()
    )
    newly = 0
    for f in rows:
        resolved = state.get(str(f.provider_comment_id))
        if resolved is True and f.status == "open":
            f.status = "resolved"
            newly += 1
        elif resolved is False and f.status == "resolved":
            f.status = "open"
    open_blocking = sum(1 for f in rows if f.status == "open" and f.severity in BLOCKING_SEVERITIES)
    s.flush()
    return BlockingState(open_blocking, newly)


def count_open_blocking(s: Session, pr_id: UUID) -> int:
    """Open blocking findings as currently recorded (no platform read)."""
    stmt = (
        select(func.count(Finding.id))
        .join(Review, Review.id == Finding.review_id)
        .where(
            Review.pr_id == pr_id,
            Finding.posted.is_(True),
            Finding.provider_comment_id.is_not(None),
            Finding.status == "open",
            Finding.severity.in_(BLOCKING_SEVERITIES),
        )
    )
    return int(s.execute(stmt).scalar_one())


def _set_status(
    platform: GitPlatform,
    ref: RepoRef,
    sha: str,
    cfg: HootPRConfig,
    state: CheckState,
    title: str,
    summary: str,
) -> None:
    if not cfg.reviews.commit_status or not sha:
        return
    try:
        platform.set_status(ref, sha, state, title, summary)
    except Exception:
        log.exception("platform_post_failed", action="set_status")


def apply_request_changes_workflow(
    s: Session,
    platform: GitPlatform,
    ref: RepoRef,
    pr: PullRequest,
    cfg: HootPRConfig,
    head_sha: str,
    *,
    force_approve: bool = False,
    read_platform: bool = True,
) -> str:
    """Re-evaluate, set the check (and approve once per transition); returns the new state."""
    result = sync_resolution(s, platform, ref, pr, read_platform=read_platform)
    previous = pr.blocking_state
    if result.open_blocking > 0:
        n = result.open_blocking
        _set_status(
            platform,
            ref,
            head_sha,
            cfg,
            "failure",
            "Changes requested",
            f"{n} blocking HootPR comment(s) unresolved.",
        )
        pr.blocking_state = "changes_requested"
    else:
        _set_status(
            platform,
            ref,
            head_sha,
            cfg,
            "success",
            "All blocking HootPR comments resolved",
            "No blocking HootPR comment is unresolved.",
        )
        if previous == "changes_requested" or (force_approve and previous != "approved"):
            try:
                platform.post_review(ref, pr.number, head_sha, APPROVE_BODY, [], event="APPROVE")
                pr.blocking_state = "approved"
            except Exception:  # state stays put: the next evaluation retries the approval
                log.exception("platform_post_failed", action="approve")
    s.flush()
    log.info(
        "blocking_state",
        previous=previous,
        state=pr.blocking_state,
        open_blocking=result.open_blocking,
        newly_resolved=result.newly_resolved,
    )
    return pr.blocking_state


def refresh_blocking(
    ctx: WorkerContext, pr_id: UUID, *, force_approve: bool = False, read_platform: bool = True
) -> str | None:
    """Re-evaluate one PR; ``None`` when the workflow is off (or the PR is gone)."""
    with ctx.session_factory() as s:
        pr = s.get(PullRequest, pr_id)
        repo = s.get(Repository, pr.repo_id) if pr is not None else None
        org = s.get(Organization, repo.org_id) if repo is not None else None
        if pr is None or repo is None or org is None:
            return None
        ref = repo_ref(repo)
        platform = ctx.platforms(s, repo)
        try:
            cfg = load_effective_config(
                platform, ref, pr.base_ref or repo.default_branch, repo.settings, org.settings
            ).config
            if not cfg.reviews.request_changes_workflow:
                return None
            head_sha = pr.head_sha
            s.rollback()  # end the read transaction before taking the PR row lock
            locked = s.get(PullRequest, pr_id, with_for_update=True, populate_existing=True)
            if locked is None:
                return None
            state = apply_request_changes_workflow(
                s,
                platform,
                ref,
                locked,
                cfg,
                locked.head_sha or head_sha,
                force_approve=force_approve,
                read_platform=read_platform,
            )
            s.commit()
            return state
        finally:
            close_platform(platform)
