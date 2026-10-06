"""Review job lifecycle (spec §6.6, decisions P6/P7).

``handle_pr_event``/``start_review`` run inside ``events.process``: refresh the PR, dedupe,
apply the auto-review rules, supersede older queued reviews, rate limit, hold credits sized from
the PR and enqueue ``review.run``. ``run_review`` holds the per-PR lock, runs the review engine
(``app.review.engine``) within that credit budget, posts the results, persists findings + trace,
then settles the hold at the metered credits (the unused part is returned); it releases the hold
when nothing was reviewable or on any error (spec §7.9).

Platform posts that happen after the DB commit are logged and never re-raised, so a flaky
provider cannot leave the ledger and the review row disagreeing.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid_utils.compat import uuid7

from app.billing.ledger import InsufficientCredits
from app.billing.pricing import estimate_review_hold, settle_amount
from app.billing.rate_limit import Limited
from app.config.loader import load_effective_config, resolve_config
from app.config.schema import HootPRConfig
from app.events.models import EventPR, PrEvent
from app.formatting.notices import (
    error_notice,
    out_of_credits_notice,
    rate_limited_notice,
    skip_title,
    skipped_notice,
)
from app.formatting.walkthrough import WALKTHROUGH_MARKER, render_no_files_notice
from app.kb.resolve import linked_repo_specs, load_external_tools
from app.knowledge.base import KnowledgeBase, NullKnowledge
from app.knowledge.learnings import SqlKnowledge, effective_scope, purge_learnings
from app.llm.types import ProviderUnavailable
from app.logging import get_logger
from app.merge.checks import PRE_MERGE_FAILED
from app.merge.stage import persist_merge_stage, run_merge_stage
from app.models import (
    AgentStep,
    Finding,
    Installation,
    LlmCall,
    Organization,
    PullRequest,
    Repository,
    Review,
    ReviewTask,
    ToolRun,
)
from app.models.base import utcnow
from app.platforms.base import CheckState, GitPlatform, RepoRef
from app.platforms.base import PullRequest as PlatformPR
from app.platforms.factory import NotInstalled, close_platform, repo_ref
from app.review.anchoring import DiffIndex, fingerprint
from app.review.blocking import (
    apply_request_changes_workflow,
    count_open_blocking,
    refresh_blocking,
)
from app.review.cache import NullCache, ReviewCache, SqlReviewCache
from app.review.engine import EngineDeps, EngineInputs, EngineResult, run_engine
from app.review.findings import Candidate
from app.review.posting import PostOutcome, make_details, post_results
from app.review.rules import AUTO_TRIGGERS, PrFacts, ReviewTrigger, should_review
from app.review.trace import SqlTraceSink, timed_stage
from app.sandbox.base import CloneError, RepoTooLarge, SandboxUnavailable
from app.security.store import surface_baseline
from app.worker.context import WorkerContext

log = get_logger(__name__)
REF_TYPE = "review"
# A review for the same (PR, head SHA) in one of these states makes a new auto review a no-op.
ACTIVE = ("queued", "running", "completed")
CRASH_FLAG = "retried_after_crash"
# Finding rows are written before posting with this status (inline ones): after a crash the
# retry reconciles them against the PR's comments instead of posting them twice (spec §7.9).
PENDING = "pending"
FRIENDLY_ERRORS: dict[type[Exception], str] = {
    RepoTooLarge: "The repository is larger than HootPR's size limit for reviews.",
    CloneError: "HootPR could not clone the repository.",
    SandboxUnavailable: "HootPR's review sandbox is unavailable right now.",
    ProviderUnavailable: "The AI provider is unavailable right now.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _friendly(exc: Exception) -> str | None:
    return next((msg for cls, msg in FRIENDLY_ERRORS.items() if isinstance(exc, cls)), None)


def _prior_fingerprints(s: Session, pr_id: UUID) -> frozenset[str]:
    """Fingerprints of open findings already posted on this PR (never reposted, spec §7.6).

    A resolved thread's finding may be reported again if the problem comes back (R8)."""
    rows = s.execute(
        select(Finding.fingerprint)
        .join(Review, Review.id == Finding.review_id)
        .where(Review.pr_id == pr_id, Finding.posted.is_(True), Finding.status == "open")
    ).scalars()
    return frozenset(rows)


def _reset_attempt(s: Session, review: Review) -> list[tuple[str, str, int, str]]:
    """Crash retry: drop the dead attempt's trace and findings (the retry records its own) and
    return its inline findings that were about to be posted: (fingerprint, path, line, title)."""
    pending = [
        (f.fingerprint, f.path, f.end_line, f.title)
        for f in s.execute(
            select(Finding).where(Finding.review_id == review.id, Finding.status == PENDING)
        ).scalars()
    ]
    for model in (Finding, AgentStep, ToolRun, ReviewTask):
        s.execute(delete(model).where(model.review_id == review.id))
    review.stages = []
    return pending


def _posted_before_crash(
    platform: GitPlatform, ref: RepoRef, number: int, pending: list[tuple[str, str, int, str]]
) -> frozenset[str]:
    """Fingerprints of pending findings whose inline comment already exists on the PR."""
    if not pending:
        return frozenset()
    comments = [c for c in platform.list_comments(ref, number) if c.path is not None]
    return frozenset(
        fp
        for fp, path, line, title in pending
        if any(c.path == path and c.line == line and f"**{title}**" in c.body for c in comments)
    )


def _safe(action: str, fn: Callable[..., object], *args: object) -> None:
    try:
        fn(*args)
    except Exception:
        log.exception("platform_post_failed", action=action)


def _status(
    platform: GitPlatform,
    ref: RepoRef,
    sha: str,
    cfg: HootPRConfig,
    state: CheckState,
    title: str,
    summary: str = "",
) -> None:
    if cfg.reviews.commit_status:
        _safe("set_status", platform.set_status, ref, sha, state, title, summary or title)


def _final_status(
    s: Session,
    platform: GitPlatform,
    ref: RepoRef,
    pr_id: UUID,
    sha: str,
    cfg: HootPRConfig,
    state: CheckState,
    title: str,
    summary: str = "",
) -> None:
    """The check for a head SHA that gets no (new) review verdict — skipped, rate limited, out
    of credits, nothing reviewable, errors. With ``request_changes_workflow`` open blocking
    findings from earlier reviews keep it failing, so a push can't turn the PR green (R18)."""
    if cfg.reviews.request_changes_workflow:
        try:
            n = count_open_blocking(s, pr_id)
        except Exception:
            log.exception("count_open_blocking_failed")
            s.rollback()
            n = 0
        if n > 0:
            _status(
                platform,
                ref,
                sha,
                cfg,
                "failure",
                "Changes requested",
                f"{n} blocking HootPR comment(s) unresolved.",
            )
            return
    _status(platform, ref, sha, cfg, state, title, summary)


def _notice(platform: GitPlatform, ref: RepoRef, number: int, body: str) -> None:
    _safe("upsert_comment", platform.upsert_comment, ref, number, WALKTHROUGH_MARKER, body)


def _apply_event_pr(pr: PullRequest, epr: EventPR) -> None:
    pr.title, pr.body, pr.state, pr.is_draft = epr.title, epr.body, epr.state, epr.is_draft
    pr.labels = list(epr.labels)
    pr.url = epr.url or pr.url
    pr.author_username = epr.author_username or pr.author_username
    pr.base_ref = epr.base_ref or pr.base_ref
    pr.head_ref = epr.head_ref or pr.head_ref
    pr.base_sha = epr.base_sha or pr.base_sha
    pr.head_sha = epr.head_sha or pr.head_sha


def upsert_pull_request(s: Session, repo: Repository, epr: EventPR) -> PullRequest:
    """Insert-or-update the PR row; concurrent first events for one PR are safe."""
    now = utcnow()
    s.execute(
        insert(PullRequest)
        .values(
            id=uuid7(),
            created_at=now,
            updated_at=now,
            repo_id=repo.id,
            number=epr.number,
            labels=[],
            reviewed_commits_count=0,
            paused=False,
        )
        .on_conflict_do_nothing(index_elements=["repo_id", "number"])
    )
    pr = s.execute(
        select(PullRequest)
        .where(PullRequest.repo_id == repo.id, PullRequest.number == epr.number)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    _apply_event_pr(pr, epr)
    s.flush()
    return pr


def cancel_queued_reviews(
    s: Session, ctx: WorkerContext, pr_id: UUID, reason: str, keep: UUID | None = None
) -> int:
    """Mark this PR's queued reviews ``skipped/<reason>`` and release their credit holds."""
    rows = (
        s.execute(
            select(Review).where(Review.pr_id == pr_id, Review.status == "queued").with_for_update()
        )
        .scalars()
        .all()
    )
    n = 0
    for r in rows:
        if r.id == keep:
            continue
        r.status, r.skip_reason, r.finished_at = "skipped", reason, _now()
        hold = ctx.ledger.find_open_reservation(s, REF_TYPE, r.id)
        if hold is not None:
            ctx.ledger.release(s, hold)
        n += 1
    s.flush()
    return n


def find_reviewable_repo(
    s: Session, provider: str, provider_repo_id: str
) -> tuple[Repository, Organization, Installation] | None:
    """The enabled repository with an active installation and an unblocked org, else ``None``."""
    repo = s.execute(
        select(Repository).where(
            Repository.provider == provider,
            Repository.provider_repo_id == provider_repo_id,
        )
    ).scalar_one_or_none()
    if repo is None or repo.installation_id is None or not repo.enabled:
        return None
    inst = s.get(Installation, repo.installation_id)
    if inst is None or inst.status != "active":
        return None
    org = s.get(Organization, repo.org_id)
    if org is None or org.blocked:
        return None
    return repo, org, inst


def _reviewable_repo(s: Session, ev: PrEvent) -> tuple[Repository, Organization] | None:
    found = find_reviewable_repo(s, ev.provider, ev.repo.provider_repo_id)
    return (found[0], found[1]) if found is not None else None


def handle_pr_event(ctx: WorkerContext, ev: PrEvent) -> str:
    """Returns the delivery status: ``processed`` or ``ignored`` (unknown/disabled repo)."""
    with ctx.session_factory() as s:
        found = _reviewable_repo(s, ev)
        if found is None:
            log.info("pr_event_ignored", repo=ev.repo.full_name, reason="unknown_or_disabled")
            return "ignored"
        repo, org = found
        pr = upsert_pull_request(s, repo, ev.pr)
        if ev.kind == "pr_updated":  # GitLab: title/labels/threads changed, no new commits
            s.commit()
            pr_id = pr.id
            refresh_blocking(ctx, pr_id)
            return "processed"
        if ev.kind == "pr_closed":
            cfg = resolve_config(None, repo.settings, org.settings).config
            if cfg.reviews.abort_on_close:
                cancel_queued_reviews(s, ctx, pr.id, "pr_closed")
            s.commit()
            return "processed"
        s.commit()
        pr_id = pr.id
    trigger: ReviewTrigger = "incremental" if ev.kind == "pr_synchronized" else "auto"
    try:
        start_review(ctx, pr_id, trigger)
    except NotInstalled:
        return "ignored"
    return "processed"


def start_review(ctx: WorkerContext, pr_id: UUID, trigger: ReviewTrigger) -> UUID | None:
    """Create the review row and decide its fate. ``None`` when nothing was created.

    Lock order everywhere is PR row -> review rows -> organization row (the ledger). Platform
    HTTP calls (refresh the PR, load ``.hootpr.yaml``) happen before the PR row is locked.
    """
    with ctx.session_factory() as s:
        pr = s.get(PullRequest, pr_id)
        if pr is None:
            return None
        repo = s.get(Repository, pr.repo_id)
        org = s.get(Organization, repo.org_id) if repo is not None else None
        if repo is None or org is None:
            return None
        number = pr.number
        platform = ctx.platforms(s, repo)
        try:
            ref = repo_ref(repo)
            live = platform.get_pull_request(ref, number)
            cfg: HootPRConfig | None = None
            if (
                live.state == "open"
                and live.head_sha
                and not _has_active_review(s, pr_id, live.head_sha, trigger)
            ):
                cfg = load_effective_config(
                    platform, ref, live.base_ref, repo.settings, org.settings
                ).config
            s.rollback()  # end the read-only transaction before taking row locks
            # Row lock: concurrent events for one PR (opened + synchronize) serialize here.
            locked = s.get(PullRequest, pr_id, with_for_update=True, populate_existing=True)
            if locked is None:
                return None
            return _start(ctx, s, platform, locked, repo, org, trigger, live, cfg)
        finally:
            close_platform(platform)


def _has_active_review(s: Session, pr_id: UUID, head_sha: str, trigger: ReviewTrigger) -> bool:
    if trigger not in AUTO_TRIGGERS:
        return False
    stmt = select(Review.id).where(
        Review.pr_id == pr_id, Review.head_sha == head_sha, Review.status.in_(ACTIVE)
    )
    return s.execute(stmt).first() is not None


def _start(
    ctx: WorkerContext,
    s: Session,
    platform: GitPlatform,
    pr: PullRequest,
    repo: Repository,
    org: Organization,
    trigger: ReviewTrigger,
    live: PlatformPR,
    cfg: HootPRConfig | None,
) -> UUID | None:
    settings = ctx.settings
    ref = repo_ref(repo)
    pr.title, pr.body, pr.author_username = live.title, live.body, live.author_username
    pr.state, pr.is_draft, pr.labels = live.state, live.is_draft, list(live.labels)
    pr.base_ref, pr.head_ref = live.base_ref, live.head_ref
    pr.base_sha, pr.head_sha = live.base_sha, live.head_sha
    pr.url = live.url or pr.url
    if pr.state != "open" or not pr.head_sha:
        s.commit()
        return None
    if cfg is None or _has_active_review(s, pr.id, pr.head_sha, trigger):
        s.commit()
        log.info("review_deduplicated", pr_id=str(pr.id), head_sha=pr.head_sha)
        return None
    # ``@hootpr review`` is incremental like a push; ``full review`` starts from the PR base.
    incremental_base = (
        pr.last_reviewed_sha if trigger in ("incremental", "command_review") else None
    )
    review = Review(
        pr_id=pr.id,
        org_id=org.id,
        trigger=trigger,
        status="queued",
        head_sha=pr.head_sha,
        base_sha=incremental_base or pr.base_sha,
    )
    s.add(review)
    s.flush()
    review_id, number, sha = review.id, pr.number, pr.head_sha
    structlog.contextvars.bind_contextvars(review_id=str(review_id), org_id=str(org.id))
    facts = PrFacts(
        pr.title,
        pr.body,
        pr.author_username,
        pr.is_draft,
        pr.base_ref,
        tuple(pr.labels),
        pr.paused,
        pr.reviewed_commits_count,
    )
    reason = should_review(cfg, facts, trigger, repo.default_branch)
    if reason is not None:
        if reason == "auto_paused":
            pr.paused = True
        review.status, review.skip_reason, review.finished_at = "skipped", reason, _now()
        s.commit()
        log.info("review_skipped", reason=reason)
        _final_status(s, platform, ref, pr.id, sha, cfg, "neutral", skip_title(reason))
        if cfg.reviews.review_status:
            _notice(platform, ref, number, skipped_notice(reason))
        return review_id
    cancel_queued_reviews(s, ctx, pr.id, "superseded", keep=review_id)
    limited = ctx.limiter.check_and_consume(org.id, "review")
    if isinstance(limited, Limited):
        review.status, review.finished_at = "rate_limited", _now()
        s.commit()
        log.info("review_rate_limited", retry_after_s=limited.retry_after_s)
        _notice(
            platform,
            ref,
            number,
            rate_limited_notice(settings.rate_limit_reviews_per_hour, limited.retry_after_s),
        )
        _final_status(s, platform, ref, pr.id, sha, cfg, "success", "Review rate limited")
        return review_id
    # Token-metered (docs/token-metered-billing.md): hold sized from the PR, settled at the
    # credits the review actually used; refused only below the minimum charge.
    estimate = estimate_review_hold(live.changed_lines, live.changed_files, settings)
    hold = ctx.ledger.reserve_up_to(
        s, org.id, estimate, settings.review_min_charge, REF_TYPE, review_id
    )
    if isinstance(hold, InsufficientCredits):
        review.status, review.finished_at = "no_credits", _now()
        s.commit()
        log.info("review_no_credits", balance=str(hold.balance))
        billing_url = f"{settings.app_base_url.rstrip('/')}/o/{org.slug}/billing"
        _notice(
            platform, ref, number, out_of_credits_notice(hold.balance, billing_url, hold.required)
        )
        _final_status(s, platform, ref, pr.id, sha, cfg, "success", "Out of credits")
        return review_id
    s.commit()
    _status(platform, ref, sha, cfg, "in_progress", "HootPR review in progress")
    try:
        ctx.queue.enqueue("review.run", str(review_id))
    except Exception as exc:
        # Never leave a queued review (and its credit hold) behind with no job to run it.
        log.exception("review_enqueue_failed")
        _fail(ctx, s, review_id, f"EnqueueFailed: {type(exc).__name__}: {exc}")
        _notice(platform, ref, number, error_notice())
        _final_status(s, platform, ref, pr.id, sha, cfg, "neutral", "HootPR hit an error")
    return review_id


def _fail(
    ctx: WorkerContext,
    s: Session,
    review_id: UUID,
    error: str,
    *,
    only_if_active: bool = False,
    charge: bool = False,
) -> bool:
    """Mark the review failed and refund its hold (``charge``: the review was delivered, so
    settle at the credits metered into ``llm_calls``). Returns whether it was marked."""
    failed = s.get(Review, review_id, with_for_update=True, populate_existing=True)
    if failed is None:
        return False
    if only_if_active and failed.status not in ("queued", "running"):
        s.rollback()
        return False
    hold = ctx.ledger.find_open_reservation(s, REF_TYPE, review_id)
    if hold is not None and charge:
        metered = s.execute(
            select(func.coalesce(func.sum(LlmCall.credits), 0)).where(
                LlmCall.review_id == review_id
            )
        ).scalar_one()
        failed.credits_charged = ctx.ledger.settle(
            s, hold, Decimal(metered or 0), ctx.settings.review_min_charge
        )
    elif hold is not None:
        ctx.ledger.release(s, hold)
    failed.status, failed.finished_at, failed.error = "failed", _now(), error[:2000]
    s.commit()
    return True


def sweep_stuck_reviews(ctx: WorkerContext, *, now: datetime | None = None) -> int:
    """Beat task: fail + refund reviews stuck in ``queued``/``running`` past the timeout (lost
    broker message, dead worker). Uses the same path as a failed run, incl. the error notice."""
    now = now or _now()
    cutoff = now - timedelta(minutes=ctx.settings.review_stuck_timeout_minutes)
    with ctx.session_factory() as s:
        ids = list(
            s.execute(
                select(Review.id).where(
                    Review.status.in_(("queued", "running")),
                    func.coalesce(Review.started_at, Review.created_at) < cutoff,
                )
            ).scalars()
        )
        s.rollback()
        n = 0
        for review_id in ids:
            if not _fail(
                ctx,
                s,
                review_id,
                "Timeout: the review timed out before it finished",
                only_if_active=True,
            ):
                continue
            n += 1
            review = s.get(Review, review_id)
            pr = s.get(PullRequest, review.pr_id) if review is not None else None
            repo = s.get(Repository, pr.repo_id) if pr is not None else None
            if review is None or pr is None or repo is None:
                continue
            log.warning("review_stuck_failed", review_id=str(review_id))
            _post_failure(ctx, s, repo, repo_ref(repo), pr.number, review.head_sha, HootPRConfig())
        return n


def run_review(ctx: WorkerContext, review_id: UUID) -> None:
    """Celery ``review.run``. Runs queued reviews; a ``running`` one found under the per-PR lock
    means its worker died (acks_late redelivery), so it is retried once (spec §7.9)."""
    with ctx.session_factory() as s:
        review = s.get(Review, review_id)
        if review is None or review.status not in ("queued", "running"):
            return
        pr_id = review.pr_id
    with (
        structlog.contextvars.bound_contextvars(review_id=str(review_id)),
        ctx.lock(f"lock:pr:{pr_id}"),
        ctx.session_factory() as s,
    ):
        _run_locked(ctx, s, review_id)


def _run_locked(ctx: WorkerContext, s: Session, review_id: UUID) -> None:
    review = s.get(Review, review_id, with_for_update=True)
    if review is None or review.status not in ("queued", "running"):
        return
    pr = s.get(PullRequest, review.pr_id)
    repo = s.get(Repository, pr.repo_id) if pr is not None else None
    org = s.get(Organization, repo.org_id) if repo is not None else None
    if pr is None or repo is None or org is None:
        return
    number, head_sha, ref = pr.number, review.head_sha, repo_ref(repo)
    crashed_before = review.status == "running"
    if crashed_before and review.degraded.get(CRASH_FLAG):
        log.warning("review_crashed_twice")
        _fail(ctx, s, review_id, "WorkerCrash: the worker crashed twice while running this review")
        _post_failure(ctx, s, repo, ref, number, head_sha, HootPRConfig())
        return
    pending: list[tuple[str, str, int, str]] = []
    if crashed_before:
        log.warning("review_retry_after_crash")
        review.degraded = {**review.degraded, CRASH_FLAG: True}
        pending = _reset_attempt(s, review)
    review.status, review.started_at = "running", _now()
    s.commit()
    structlog.contextvars.bind_contextvars(org_id=str(org.id))
    cfg = HootPRConfig()
    platform: GitPlatform | None = None
    sink = SqlTraceSink(ctx.session_factory, review_id)
    pr_id, repo_id, org_id = pr.id, repo.id, org.id
    delivered = False
    try:
        platform = ctx.platforms(s, repo)
        with timed_stage(sink, "config") as st:
            resolved = load_effective_config(
                platform, ref, pr.base_ref, repo.settings, org.settings, head_sha=head_sha
            )
            st.detail = f"source: {resolved.source}"
        cfg = resolved.config
        engine_cfg, knowledge = resolve_knowledge(ctx, s, cfg, org, repo)
        linked, _ignored = linked_repo_specs(s, cfg, org.id, repo.id, ctx.settings)
        external = load_external_tools(s, ctx.crypto, ctx.settings, org.id, cfg)
        baseline = surface_baseline(s, repo.id)  # phase 6: latest attack surface map
        hold = ctx.ledger.find_open_reservation(s, REF_TYPE, review_id)
        reserved = hold.amount if hold else None  # the engine's credit budget
        live = platform.get_pull_request(ref, number)
        incremental = (
            review.trigger in ("incremental", "command_review")
            and bool(review.base_sha)
            and review.base_sha != live.base_sha
        )
        base = (review.base_sha or live.base_sha) if incremental else live.base_sha
        prior = _prior_fingerprints(s, pr_id) | _posted_before_crash(platform, ref, number, pending)
        cache: ReviewCache = (
            NullCache()
            if cfg.reviews.disable_cache
            else SqlReviewCache(ctx.session_factory, repo_id)
        )
        s.commit()  # no transaction stays open during the (long) engine run
        inputs = EngineInputs(
            review_id,
            org_id,
            ref,
            live,
            base,
            head_sha,
            incremental,
            engine_cfg,
            resolved.source,
            tuple(resolved.warnings),
            prior,
            reserved,
            linked_repos=linked,
            surface_baseline=baseline,
        )
        deps = EngineDeps(
            platform, ctx.sandboxes, ctx.llm(), sink, ctx.settings, cache=cache,
            knowledge=knowledge, external_tools=external,
        )  # fmt: skip
        try:
            result = run_engine(inputs, deps)
        finally:
            if external is not None:
                external.close()
        if result.status == "no_reviewable_files":
            _finish_no_files(ctx, s, review_id, pr_id, head_sha, result)
            log.info("review_skipped", reason="no_reviewable_files")
            if cfg.reviews.review_status:
                _notice(platform, ref, number, render_no_files_notice(result.skipped, head_sha))
            _final_status(
                s,
                platform,
                ref,
                pr_id,
                head_sha,
                cfg,
                "neutral",
                skip_title("no_reviewable_files"),
            )
            return
        with timed_stage(sink, "merge_checks") as st:
            merge = run_merge_stage(
                ctx, s, platform, ref, repo, org, pr_id, review_id, live, result, engine_cfg
            )
            st.detail = f"{len(merge.checks)} checks, {len(merge.issues)} linked issues"
        with timed_stage(sink, "post") as st:
            rows = _persist_pending(s, review_id, result.candidates)
            outcome = post_results(
                platform,
                ref,
                number,
                head_sha,
                result,
                cfg,
                make_details(result, inputs, _charge(ctx, result, reserved), reserved),
                resolved.warnings,
                diff=DiffIndex(result.files),
                pr_title=live.title,
                extra_sections=merge.sections,
            )
            delivered = True
            st.detail = f"{outcome.posted} inline, {len(outcome.unposted)} moved to the walkthrough"
        with timed_stage(sink, "close") as st:
            try:
                _persist_success(ctx, s, review_id, pr_id, head_sha, result, outcome, rows)
            except Exception:
                s.rollback()  # release the row locks before the trace sink writes the stage
                raise
            if result.sandbox_peak_mb:
                st.detail = f"sandbox peak {result.sandbox_peak_mb} MB"
        if cfg.reviews.request_changes_workflow:
            # Covers older unresolved blocking findings too (R18).
            _apply_blocking(ctx, platform, ref, pr_id, cfg, head_sha)
        else:
            _status(
                platform,
                ref,
                head_sha,
                cfg,
                "success",
                "Review completed",
                f"{outcome.posted} actionable comment(s) posted; "
                f"{len(result.additional)} additional in the walkthrough.",
            )
        persist_merge_stage(
            ctx, s, platform, ref, repo, org, pr_id, review_id, live, result, engine_cfg, merge
        )
        if merge.blocking:  # pre-merge checks in `error` mode failed (spec §10.2)
            _status(
                platform, ref, head_sha, cfg, "failure", PRE_MERGE_FAILED,
                "Pre-merge checks in error mode failed; see the HootPR walkthrough.",
            )  # fmt: skip
        log.info(
            "review_completed",
            posted=outcome.posted,
            files=len(result.reviewed_files),
            sandbox_peak_mb=result.sandbox_peak_mb,
        )
    except Exception as exc:
        s.rollback()
        log.exception("review_failed")
        # The review already reached the PR: charge it and keep the walkthrough (an error
        # notice would overwrite it).
        _fail(ctx, s, review_id, f"{type(exc).__name__}: {exc}", charge=delivered)
        if platform is not None and not delivered:
            _notice(platform, ref, number, error_notice(_friendly(exc)))
            _final_status(s, platform, ref, pr_id, head_sha, cfg, "neutral", "HootPR hit an error")
    finally:
        if platform is not None:
            close_platform(platform)


def _apply_blocking(
    ctx: WorkerContext,
    platform: GitPlatform,
    ref: RepoRef,
    pr_id: UUID,
    cfg: HootPRConfig,
    head_sha: str,
) -> None:
    try:
        with ctx.session_factory() as s2:
            locked = s2.get(PullRequest, pr_id, with_for_update=True)
            if locked is not None:
                apply_request_changes_workflow(s2, platform, ref, locked, cfg, head_sha)
                s2.commit()
    except Exception:  # the review is already delivered and charged
        log.exception("request_changes_workflow_failed")


def resolve_knowledge(
    ctx: WorkerContext, s: Session, cfg: HootPRConfig, org: Organization, repo: Repository
) -> tuple[HootPRConfig, KnowledgeBase]:
    """The engine's config + knowledge base, honouring both opt-out switches (spec §8, R15).

    ``knowledge_base.opt_out`` in the repository configuration deletes the repository's learnings;
    the org switch (dashboard) already deleted the org's. Either way no learnings are retrieved
    and no code guidelines are read."""
    if cfg.knowledge_base.opt_out:
        n = purge_learnings(s, org.id, repo.id)
        s.commit()
        if n:
            log.info("learnings_purged_repo_opt_out", deleted=n)
    if cfg.knowledge_base.opt_out or org.knowledge_base_opt_out:
        kb = cfg.knowledge_base.model_copy(update={"opt_out": True})
        return cfg.model_copy(update={"knowledge_base": kb}), NullKnowledge()
    mode = effective_scope(cfg.knowledge_base.learnings.scope, repo.private)
    knowledge = SqlKnowledge(
        ctx.session_factory, ctx.llm(), ctx.settings, org_id=org.id, repo_id=repo.id, mode=mode
    )
    return cfg, knowledge


def _finish_no_files(
    ctx: WorkerContext,
    s: Session,
    review_id: UUID,
    pr_id: UUID,
    head_sha: str,
    result: EngineResult,
) -> None:
    """Nothing to review is nothing to charge (plan Q12): release the hold, advance the PR."""
    s.execute(select(PullRequest.id).where(PullRequest.id == pr_id).with_for_update())
    review = s.get(Review, review_id, with_for_update=True, populate_existing=True)
    pr = s.get(PullRequest, pr_id)
    if review is None or pr is None:  # pragma: no cover - rows cannot vanish under the lock
        s.rollback()
        return
    hold = ctx.ledger.find_open_reservation(s, REF_TYPE, review_id)
    if hold is not None:
        ctx.ledger.release(s, hold)
    review.status, review.skip_reason, review.finished_at = "skipped", "no_reviewable_files", _now()
    review.files_considered = len(result.files)
    pr.last_reviewed_sha = head_sha
    s.commit()


def _persist_pending(s: Session, review_id: UUID, cands: list[Candidate]) -> list[UUID]:
    """Write every candidate before anything is posted (inline ones as ``pending``) and commit,
    so a crash during/after posting leaves a record the retry can reconcile."""
    rows: list[Finding] = []
    for c in cands:
        row = Finding(
            review_id=review_id,
            task_id=c.task_id,
            path=c.path[:1000],
            start_line=c.start_line,
            end_line=c.end_line,
            side="RIGHT",
            severity=c.severity,
            category=c.category,
            title=c.title[:500],
            body=c.body[:5000],
            suggestion=c.suggestion,
            source=c.source[:32],
            confidence=c.confidence,
            judge_verdict=c.verdict,
            judge_reason=c.reason[:1000] if c.reason else None,
            posted=False,
            status=PENDING if c.placement == "inline" else "open",
            evidence=list(c.evidence),
            fingerprint=c.fingerprint or fingerprint(c.path, str(c.end_line), c.category),
        )
        s.add(row)
        rows.append(row)
    s.flush()
    ids = [r.id for r in rows]
    s.commit()
    return ids


def _charge(ctx: WorkerContext, result: EngineResult, reserved: Decimal | None) -> Decimal:
    """What ``_persist_success`` will settle (shown in the walkthrough before it runs)."""
    if reserved is None:
        return Decimal(0)
    return settle_amount(result.credits, ctx.settings.review_min_charge, reserved)


def _persist_success(
    ctx: WorkerContext,
    s: Session,
    review_id: UUID,
    pr_id: UUID,
    head_sha: str,
    result: EngineResult,
    outcome: PostOutcome,
    rows: list[UUID],
) -> None:
    # Lock order PR -> review -> organization (as in start_review) or they can deadlock.
    s.execute(select(PullRequest.id).where(PullRequest.id == pr_id).with_for_update())
    review = s.get(Review, review_id, with_for_update=True, populate_existing=True)
    pr = s.get(PullRequest, pr_id, populate_existing=True)
    if review is None or pr is None:  # pragma: no cover - rows cannot vanish under the lock
        raise RuntimeError("review or pull request row disappeared")
    for c, row_id in zip(result.candidates, rows, strict=True):
        # Posting may have re-anchored a comment (and dropped its suggestion).
        s.execute(
            update(Finding)
            .where(Finding.id == row_id)
            .values(
                start_line=c.start_line,
                end_line=c.end_line,
                suggestion=c.suggestion,
                posted=c.posted,
                provider_comment_id=c.provider_comment_id,
                status="open",
            )
        )
    hold = ctx.ledger.find_open_reservation(s, REF_TYPE, review_id)
    if hold is not None:
        review.credits_charged = ctx.ledger.settle(
            s, hold, result.credits, ctx.settings.review_min_charge
        )
    review.status, review.finished_at = "completed", _now()
    review.files_considered, review.files_reviewed = len(result.files), len(result.reviewed_files)
    review.findings_posted = outcome.posted
    review.input_tokens, review.cached_tokens = (
        result.usage.input_tokens,
        result.usage.cached_tokens,
    )
    review.output_tokens, review.cost_usd = result.usage.output_tokens, result.cost_usd
    review.degraded = {**(review.degraded or {}), **result.degraded}
    pr.walkthrough_comment_id = outcome.walkthrough_id
    pr.last_reviewed_sha = head_sha
    pr.reviewed_commits_count += 1
    s.commit()


def _post_failure(
    ctx: WorkerContext,
    s: Session,
    repo: Repository,
    ref: RepoRef,
    number: int,
    head_sha: str,
    cfg: HootPRConfig,
) -> None:
    try:
        platform = ctx.platforms(s, repo)
    except Exception:
        log.exception("platform_unavailable")
        return
    try:
        _notice(platform, ref, number, error_notice())
        _status(platform, ref, head_sha, cfg, "neutral", "HootPR hit an error")
    finally:
        close_platform(platform)
