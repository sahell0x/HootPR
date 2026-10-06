"""What each ``@hootpr`` command does (spec §8, phase-3 spec §4).

Deterministic commands run inline in ``events.process`` and are free (``review``/``full review``
go through the normal review path and its metered hold). Free-form chat, ``summary`` and
``generate sequence diagram`` need the LLM: they take one ``chat`` rate-limit slot, hold up to
``CHAT_HOLD_MAX`` (settled at the metered credits) and are queued as ``chat.run`` (R1, R2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.ledger import InsufficientCredits
from app.billing.rate_limit import Limited
from app.chat.commands import ParsedComment, spec_for
from app.chat.identity import BotIdentity, primary_mention
from app.chat.replies import (
    INCREMENTAL_NOTE,
    RateLimitInfo,
    chat_marker,
    render_actions,
    render_chat_out_of_credits,
    render_chat_rate_limited,
    render_configuration_reply,
    render_help,
    render_hint,
    render_rate_limit,
    render_unsupported,
)
from app.config.loader import ResolvedConfig
from app.config.render import render_configuration
from app.config.schema import HootPRConfig
from app.events.models import CommentCreated
from app.formatting.notices import skip_title
from app.logging import get_logger
from app.models import ChatMessage, Finding, Organization, PullRequest, Repository, Review
from app.models.base import utcnow
from app.platforms.base import GitPlatform, RepoRef
from app.platforms.factory import NotInstalled
from app.review.blocking import refresh_blocking
from app.review.pipeline import start_review
from app.worker.context import WorkerContext

log = get_logger(__name__)
CHAT_REF_TYPE = "chat"
CHAT_TASK = "chat.run"
# Commands that change the PR / review state, spend review credits or reveal the org's balance:
# only commenters with write access may run them. Everyone else gets help, configuration and
# plain Q&A (without the add_learning tool).
WRITE_COMMANDS = frozenset(
    {
        "review",
        "full_review",
        "pause",
        "resume",
        "resolve",
        "approve",
        "summary",
        "rate_limit",
        "finishing_touch",
        "ignore_pre_merge",
        "create_issue",
        "security_review",
    }
)
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def needs_write_check(command: str | None) -> bool:
    return command is None or command in WRITE_COMMANDS


def commenter_can_write(platform: GitPlatform, ref: RepoRef, ev: CommentCreated) -> bool:
    """GitHub's ``author_association`` when it proves write access, else the platform's
    permission lookup; any lookup failure counts as no access (fail closed)."""
    if ev.provider == "github" and (ev.author_association or "") in TRUSTED_ASSOCIATIONS:
        return True
    try:
        return platform.can_write(ref, ev.author_username)
    except Exception:
        log.warning("permission_lookup_failed", exc_info=True)
        return False


@dataclass
class CommandContext:
    ctx: WorkerContext
    s: Session
    platform: GitPlatform
    ref: RepoRef
    repo: Repository
    org: Organization
    pr: PullRequest
    row: ChatMessage
    ev: CommentCreated
    parsed: ParsedComment
    cfg: HootPRConfig
    resolved: ResolvedConfig
    identity: BotIdentity

    @property
    def author(self) -> str:
        return self.ev.author_username

    @property
    def mention(self) -> str:
        return primary_mention(self.identity)

    def billing_url(self) -> str:
        return f"{self.ctx.settings.app_base_url.rstrip('/')}/o/{self.org.slug}/billing"


def post_reply(
    platform: GitPlatform, ref: RepoRef, number: int, row: ChatMessage, body: str
) -> str:
    """Reply in the comment's thread (review comments, every GitLab note) or top-level."""
    meta: dict[str, Any] = row.meta or {}
    if row.thread_ref and (meta.get("provider") == "gitlab" or meta.get("is_review_comment")):
        return platform.reply_to_comment(ref, number, row.thread_ref, body)
    return platform.upsert_comment(ref, number, chat_marker(row.id), body)


def _finish(c: CommandContext, body: str, status: str = "completed") -> None:
    c.s.commit()  # nothing stays locked while the platform is called
    row = c.row  # expired by the commit: reloads current values on access
    try:
        row.reply_comment_id = post_reply(c.platform, c.ref, c.pr.number, row, body)
        row.status = status
    except Exception as exc:
        log.exception("chat_reply_failed")
        row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
    row.finished_at = utcnow()
    c.s.commit()


def resolve_hootpr_threads(platform: GitPlatform, ref: RepoRef, s: Session, pr: PullRequest) -> int:
    """Resolve every posted, open HootPR finding thread (best effort per thread)."""
    rows = (
        s.execute(
            select(Finding)
            .join(Review, Review.id == Finding.review_id)
            .where(
                Review.pr_id == pr.id,
                Finding.posted.is_(True),
                Finding.status == "open",
                Finding.provider_comment_id.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    done: set[str] = set()
    failed: set[str] = set()
    for f in rows:
        ref_id = str(f.provider_comment_id)
        if ref_id in failed:
            continue
        if ref_id not in done:
            try:
                platform.resolve_thread(ref, pr.number, ref_id)
            except Exception:
                log.warning("resolve_thread_failed", thread=ref_id, exc_info=True)
                failed.add(ref_id)
                continue
            done.add(ref_id)
        f.status = "resolved"
    s.flush()
    return len(done)


# --- deterministic commands -------------------------------------------------------------


def _review(c: CommandContext) -> None:
    full = c.parsed.command == "full_review"
    c.s.commit()  # start_review opens its own sessions and locks the PR row
    try:
        review_id = start_review(c.ctx, c.pr.id, "command_full" if full else "command_review")
    except NotInstalled:
        review_id = None
    review = c.s.get(Review, review_id, populate_existing=True) if review_id else None
    if review is None:
        body = render_hint(
            c.author, "No review was started: the pull request is closed or has no commits."
        )
    elif review.status == "queued":
        if full:
            body = render_actions(c.author, ["Full review triggered."])
        else:
            note = INCREMENTAL_NOTE.format(mention=c.mention)
            body = render_actions(c.author, ["Review triggered."], note)
    elif review.status == "skipped":
        body = render_hint(
            c.author, f"No review was started — {skip_title(review.skip_reason or '')}."
        )
    elif review.status == "rate_limited":
        body = render_hint(
            c.author,
            f"Review rate limited — see the HootPR comment on this pull request or use "
            f"`{c.mention} rate limit`.",
        )
    elif review.status == "no_credits":
        body = render_hint(c.author, f"Out of credits — an admin can top up at {c.billing_url()}.")
    else:
        body = render_hint(c.author, "HootPR could not start the review, no credit was charged.")
    _finish(c, body)


def _pause(c: CommandContext) -> None:
    c.pr.paused = True
    _finish(c, render_actions(c.author, ["Reviews paused."]))


def _resume(c: CommandContext) -> None:
    c.pr.paused = False
    c.pr.reviewed_commits_count = 0
    _finish(c, render_actions(c.author, ["Reviews resumed."]))


def _resolve_or_approve(c: CommandContext) -> None:
    if c.ev.is_review_comment:
        verb = c.parsed.command or "resolve"
        _finish(
            c,
            render_hint(c.author, f"Use `{c.mention} {verb}` in a top-level pull request comment."),
        )
        return
    resolve_hootpr_threads(c.platform, c.ref, c.s, c.pr)
    c.s.commit()
    workflow = c.cfg.reviews.request_changes_workflow
    if c.parsed.command == "approve":
        if workflow:
            state = refresh_blocking(c.ctx, c.pr.id, force_approve=True, read_platform=False)
            if state == "approved":
                body = render_actions(c.author, ["Comments resolved and changes approved."])
            else:
                body = render_actions(
                    c.author,
                    ["Comments resolved."],
                    "Some blocking HootPR threads could not be resolved, so the pull request "
                    "was not approved. Resolve them and try again.",
                )
        else:
            body = render_actions(
                c.author,
                ["Comments resolved."],
                "Approval requires `reviews.request_changes_workflow: true`.",
            )
    else:
        if workflow:
            refresh_blocking(c.ctx, c.pr.id, read_platform=False)
        body = render_actions(c.author, ["Comments resolved."])
    _finish(c, body)


def _configuration(c: CommandContext) -> None:
    body = render_configuration_reply(
        c.author, render_configuration(c.resolved), c.resolved.warnings
    )
    _finish(c, body)


def _help(c: CommandContext) -> None:
    schema_url = f"{c.ctx.settings.api_base_url.rstrip('/')}/schema/hootpr.v1.json"
    _finish(c, f"@{c.author}\n\n{render_help(c.mention, schema_url)}")


def _rate_limit(c: CommandContext) -> None:
    lim, settings, org_id = c.ctx.limiter, c.ctx.settings, c.org.id
    info = RateLimitInfo(
        reviews_limit=settings.rate_limit_reviews_per_hour,
        reviews_remaining=lim.remaining(org_id, "review"),
        reviews_retry_s=lim.retry_after(org_id, "review"),
        chat_limit=settings.rate_limit_chat_per_hour,
        chat_remaining=lim.remaining(org_id, "chat"),
        chat_retry_s=lim.retry_after(org_id, "chat"),
        balance=c.ctx.ledger.balance(c.s, org_id),
        typical_review=settings.credits_typical_review,
        typical_chat=settings.credits_typical_chat_reply,
        billing_url=c.billing_url(),
    )
    _finish(c, render_rate_limit(c.author, info))


def _ignore(c: CommandContext) -> None:
    _finish(
        c,
        render_hint(
            c.author,
            f"`{c.mention} ignore` only works in the pull request description; add it there "
            "to stop reviews of this PR.",
        ),
    )


def _finishing_touch(c: CommandContext) -> None:
    from app.finishing.handler import handle_finishing  # the handler imports this module

    handle_finishing(c)


def _ignore_pre_merge(c: CommandContext) -> None:
    from app.merge.ignore import handle_ignore_pre_merge  # imports this module

    handle_ignore_pre_merge(c)


def _security_review(c: CommandContext) -> None:
    from app.security.commands import handle_security_review  # imports this module

    handle_security_review(c)


def _unsupported(c: CommandContext) -> None:
    _finish(c, render_unsupported(c.author, c.parsed.phrase))


# --- LLM work -----------------------------------------------------------------------------


def queue_llm_job(c: CommandContext) -> None:
    """Chat rate limit -> metered hold (up to ``chat_hold_max``) -> ``chat.run`` (the hold is
    settled at the metered credits, or released on failure)."""
    settings = c.ctx.settings
    limited = c.ctx.limiter.check_and_consume(c.org.id, "chat")
    if isinstance(limited, Limited):
        log.info("chat_rate_limited", retry_after_s=limited.retry_after_s)
        body = render_chat_rate_limited(
            c.author, settings.rate_limit_chat_per_hour, limited.retry_after_s
        )
        _finish(c, body, status="rate_limited")
        return
    hold = c.ctx.ledger.reserve_up_to(
        c.s, c.org.id, settings.chat_hold_max, settings.chat_min_charge, CHAT_REF_TYPE, c.row.id
    )
    if isinstance(hold, InsufficientCredits):
        log.info("chat_no_credits", balance=str(hold.balance))
        body = render_chat_out_of_credits(
            c.author, hold.balance, settings.chat_min_charge, c.billing_url()
        )
        _finish(c, body, status="no_credits")
        return
    c.row.status = "queued"
    c.s.commit()
    try:
        c.ctx.queue.enqueue(CHAT_TASK, str(c.row.id))
    except Exception as exc:
        log.exception("chat_enqueue_failed")
        held = c.ctx.ledger.find_open_reservation(c.s, CHAT_REF_TYPE, c.row.id)
        if held is not None:
            c.ctx.ledger.release(c.s, held)
        c.row.error = f"EnqueueFailed: {type(exc).__name__}: {exc}"[:2000]
        _finish(
            c,
            render_hint(c.author, "HootPR could not answer right now, no credit was charged."),
            status="failed",
        )


_HANDLERS: dict[str, Callable[[CommandContext], None]] = {
    "review": _review,
    "full_review": _review,
    "pause": _pause,
    "resume": _resume,
    "resolve": _resolve_or_approve,
    "approve": _resolve_or_approve,
    "configuration": _configuration,
    "help": _help,
    "rate_limit": _rate_limit,
    "ignore": _ignore,
    "unsupported": _unsupported,
    "finishing_touch": _finishing_touch,
    "ignore_pre_merge": _ignore_pre_merge,
    "security_review": _security_review,
}


def run_command(c: CommandContext) -> None:
    """Execute the parsed comment: a deterministic command inline, else queue the LLM job."""
    name = c.parsed.command
    if name in WRITE_COMMANDS and (c.row.meta or {}).get("can_write") is not True:
        log.info("command_refused", command=name, reason="no_write_access")
        phrase = c.parsed.phrase if name == "finishing_touch" else spec_for(name).phrases[0]
        _finish(
            c,
            render_hint(
                c.author,
                f"`{c.mention} {phrase}` needs write access to this repository. "
                f"You can still ask questions or use `{c.mention} help`.",
            ),
        )
        return
    if name is None or (name != "unsupported" and spec_for(name).cost == "chat"):
        queue_llm_job(c)
        return
    _HANDLERS[name](c)
