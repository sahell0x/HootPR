"""Comment webhooks -> commands or chat (phase-3 spec §3).

Order: known repo -> loop guard (R4) -> parse -> PR row -> addressed to HootPR (a mention, or
any reply in a HootPR thread with ``chat.auto_reply``) -> one ``chat_messages`` row per
(PR, comment) (redeliveries are no-ops) -> 👀 reaction -> command / chat job.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid_utils.compat import uuid7

from app.chat.actions import (
    CHAT_REF_TYPE,
    CommandContext,
    commenter_can_write,
    needs_write_check,
    post_reply,
    run_command,
)
from app.chat.commands import parse_comment
from app.chat.identity import bot_identity, is_bot_author
from app.config.loader import load_effective_config
from app.events.models import CommentCreated, EventPR
from app.logging import get_logger
from app.models import ChatMessage, Finding, PullRequest, Review
from app.models.base import utcnow
from app.platforms.base import ProviderName
from app.platforms.factory import NotInstalled, close_platform, repo_ref
from app.review.pipeline import find_reviewable_repo, upsert_pull_request
from app.worker.context import WorkerContext

log = get_logger(__name__)
DIFF_HUNK_MAX = 4000
__all__ = [
    "CHAT_REF_TYPE",
    "comment_meta",
    "handle_comment_event",
    "is_hootpr_thread",
    "post_reply",
]


def is_hootpr_thread(s: Session, pr_id: UUID, thread_ref: str) -> bool:
    """A thread HootPR started (a posted finding) or already replied in."""
    finding = s.execute(
        select(Finding.id)
        .join(Review, Review.id == Finding.review_id)
        .where(
            Review.pr_id == pr_id,
            Finding.posted.is_(True),
            Finding.provider_comment_id == thread_ref,
        )
        .limit(1)
    ).first()
    if finding is not None:
        return True
    replied = s.execute(
        select(ChatMessage.id)
        .where(
            ChatMessage.pr_id == pr_id,
            ChatMessage.thread_ref == thread_ref,
            ChatMessage.reply_comment_id.is_not(None),
        )
        .limit(1)
    ).first()
    return replied is not None


def comment_meta(ev: CommentCreated) -> dict[str, Any]:
    return {
        "provider": ev.provider,
        "is_review_comment": ev.is_review_comment,
        "path": ev.path,
        "line": ev.line,
        "diff_hunk": (ev.diff_hunk or "")[:DIFF_HUNK_MAX] or None,
        "url": ev.url,
    }


def _reaction_ref(ev: CommentCreated) -> str:
    if ev.provider == "gitlab":
        return f"{ev.pr_number}:{ev.comment_id}"
    return f"review:{ev.comment_id}" if ev.is_review_comment else ev.comment_id


def _command_value(parsed_command: str | None, phrase: str) -> str | None:
    if parsed_command == "unsupported":
        return f"unsupported:{phrase}"[:64]
    return parsed_command


def handle_comment_event(ctx: WorkerContext, ev: CommentCreated) -> str:
    """Returns the delivery status: ``processed`` or ``ignored``."""
    with ctx.session_factory() as s:
        found = find_reviewable_repo(s, ev.provider, ev.repo.provider_repo_id)
        if found is None:
            log.info("comment_ignored", reason="unknown_or_disabled_repo")
            return "ignored"
        repo, org, inst = found
        provider: ProviderName = ev.provider
        identity = bot_identity(ctx.settings, provider, inst.gitlab_bot_username)
        if is_bot_author(identity, ev.author_username):
            log.info("comment_ignored", reason="bot_author")
            return "ignored"
        parsed = parse_comment(ev.body, identity)
        if not parsed.mentioned and ev.thread_ref is None:
            return "ignored"  # a plain top-level comment is never addressed to HootPR
        ref = repo_ref(repo)
        try:
            platform = ctx.platforms(s, repo)
        except NotInstalled:
            return "ignored"
        try:
            pr = s.execute(
                select(PullRequest).where(
                    PullRequest.repo_id == repo.id, PullRequest.number == ev.pr_number
                )
            ).scalar_one_or_none()
            if pr is None:
                if not parsed.mentioned:
                    return "ignored"  # HootPR never posted here: not one of its threads
                live = platform.get_pull_request(ref, ev.pr_number)
                pr = upsert_pull_request(
                    s,
                    repo,
                    EventPR(
                        number=live.number,
                        title=live.title,
                        body=live.body,
                        author_username=live.author_username,
                        state=live.state,
                        is_draft=live.is_draft,
                        base_ref=live.base_ref,
                        head_ref=live.head_ref,
                        base_sha=live.base_sha,
                        head_sha=live.head_sha,
                        labels=list(live.labels),
                        url=live.url,
                    ),
                )
                s.commit()
            bot_thread = ev.thread_ref is not None and is_hootpr_thread(s, pr.id, ev.thread_ref)
            if not parsed.mentioned and not bot_thread:
                return "ignored"
            resolved = load_effective_config(
                platform, ref, pr.base_ref or repo.default_branch, repo.settings, org.settings
            )
            cfg = resolved.config
            if not parsed.mentioned and not cfg.chat.auto_reply:
                return "ignored"
            meta = comment_meta(ev)
            if needs_write_check(parsed.command):
                meta["can_write"] = commenter_can_write(platform, ref, ev)
            now = utcnow()
            row_id = s.execute(
                insert(ChatMessage)
                .values(
                    id=uuid7(),
                    created_at=now,
                    updated_at=now,
                    org_id=org.id,
                    pr_id=pr.id,
                    provider_comment_id=ev.comment_id,
                    thread_ref=ev.thread_ref,
                    author_username=ev.author_username[:255],
                    kind="command" if parsed.command else "chat",
                    command=_command_value(parsed.command, parsed.phrase),
                    body=ev.body[:20000],
                    status="received",
                    meta=meta,
                )
                .on_conflict_do_nothing(index_elements=["pr_id", "provider_comment_id"])
                .returning(ChatMessage.id)
            ).scalar_one_or_none()
            if row_id is None:
                s.rollback()
                log.info("comment_ignored", reason="duplicate")
                return "ignored"
            s.commit()
            row = s.get(ChatMessage, row_id)
            if row is None:  # pragma: no cover - just inserted and committed
                return "ignored"
            try:
                platform.add_reaction(ref, _reaction_ref(ev), "eyes")
            except Exception:
                log.warning("reaction_failed", exc_info=True)
            log.info("comment_accepted", kind=row.kind, command=row.command)
            run_command(
                CommandContext(
                    ctx=ctx,
                    s=s,
                    platform=platform,
                    ref=ref,
                    repo=repo,
                    org=org,
                    pr=pr,
                    row=row,
                    ev=ev,
                    parsed=parsed,
                    cfg=cfg,
                    resolved=resolved,
                    identity=identity,
                )
            )
            return "processed"
        finally:
            close_platform(platform)
