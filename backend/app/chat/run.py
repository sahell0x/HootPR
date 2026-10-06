"""``chat.run``: answer one queued chat message (spec §8, phase-3 spec §5, R2, R10, R23-R25).

The router already took a ``chat`` rate-limit slot and held up to ``CHAT_HOLD_MAX`` credits
(``ref_type="chat"``, ``ref_id=chat_message_id``). Here the hold is settled at the metered
credits once the reply is posted and released on any HootPR-side failure (a friendly "no credit
was charged" reply is posted instead). The sandbox is created only when the agent calls a sandbox
tool and is always destroyed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.actions import CHAT_REF_TYPE, post_reply
from app.chat.agent import AddLearningFn, ChatContext, run_chat_agent
from app.chat.commands import SEQUENCE_DIAGRAM_REQUEST, parse_comment
from app.chat.identity import bot_identity
from app.chat.replies import render_actions, render_chat_error, render_chat_reply
from app.chat.sandbox import LazySandbox
from app.chat.summary import regenerate_summary
from app.config.loader import load_effective_config
from app.formatting.walkthrough import WALKTHROUGH_MARKER
from app.kb.external import ExternalTools
from app.kb.resolve import load_external_tools
from app.knowledge.base import Embedder, KnowledgeBase, LearningHit, NullKnowledge
from app.knowledge.learnings import AddedLearning, SqlKnowledge, add_learning
from app.knowledge.text import redact_secrets
from app.llm.types import TraceContext
from app.logging import get_logger
from app.models import ChatMessage, Finding, PullRequest, Repository, Review
from app.models.base import utcnow
from app.platforms.base import CloneCredentials, Comment, GitPlatform, RepoRef
from app.platforms.factory import close_platform, repo_ref
from app.review.agent import AgentLimits, Toolbox
from app.review.graph import CodeGraph
from app.review.llm import MeteredLLM
from app.review.pipeline import find_reviewable_repo, resolve_knowledge
from app.review.safety import harden_text, repo_host, scrub_urls
from app.review.tool_results import ToolResults
from app.settings import Settings
from app.worker.context import WorkerContext

log = get_logger(__name__)
FINDING_MAX_CHARS = 3000
SUMMARY_DONE = "Summary regenerated."
SUMMARY_SKIPPED = (
    "No summary was generated: `reviews.high_level_summary` is off or nothing is reviewable."
)


class ChatAborted(Exception):
    """The chat cannot run (repository uninstalled/disabled, rows gone, worker crash)."""


@dataclass
class _Run:
    """Per-run state the failure path needs."""

    author: str = ""
    platform: GitPlatform | None = None
    ref: RepoRef | None = None
    number: int = 0
    lazy: LazySandbox | None = None
    secrets: list[str] = field(default_factory=list)
    delivered: bool = False
    external: ExternalTools | None = None


def run_chat(ctx: WorkerContext, chat_id: UUID) -> None:
    """Celery ``chat.run``. Runs ``queued`` rows; a ``running`` row means the worker died
    mid-answer (acks_late redelivery): it is failed and refunded, never answered twice."""
    with (
        structlog.contextvars.bound_contextvars(chat_id=str(chat_id)),
        ctx.session_factory() as s,
    ):
        row = s.get(ChatMessage, chat_id, with_for_update=True)
        if row is None or row.status not in ("queued", "running"):
            return
        crashed = row.status == "running"
        row.status = "running"
        s.commit()
        _run(ctx, s, chat_id, crashed)


def _run(ctx: WorkerContext, s: Session, chat_id: UUID, crashed: bool) -> None:
    st = _Run()
    llm: MeteredLLM | None = None
    try:
        row = s.get(ChatMessage, chat_id)
        pr = s.get(PullRequest, row.pr_id) if row is not None else None
        repo = s.get(Repository, pr.repo_id) if pr is not None else None
        if row is None or pr is None or repo is None:
            raise ChatAborted("the pull request is gone")
        st.author, st.number = row.author_username, pr.number
        found = find_reviewable_repo(s, repo.provider, repo.provider_repo_id)
        if found is None:
            raise ChatAborted("the repository is no longer enabled")
        _, org, inst = found
        st.ref = repo_ref(repo)
        st.platform = ctx.platforms(s, repo)
        if crashed:
            raise ChatAborted("WorkerCrash: the worker stopped while answering")
        platform, ref = st.platform, st.ref
        live = platform.get_pull_request(ref, pr.number)
        resolved = load_effective_config(
            platform, ref, live.base_ref or repo.default_branch, repo.settings, org.settings
        )
        cfg, knowledge = resolve_knowledge(ctx, s, resolved.config, org, repo)
        opted_out = isinstance(knowledge, NullKnowledge)
        llm = MeteredLLM(ctx.llm())
        if isinstance(knowledge, SqlKnowledge):
            # learning retrieval + add_learning embeddings count toward this chat's cost
            knowledge = knowledge.bind_embedder(llm)
        trace = TraceContext(org_id=org.id, chat_id=row.id, stage="chat")
        st.external = load_external_tools(s, ctx.crypto, ctx.settings, org.id, cfg)
        s.commit()  # nothing stays locked during LLM calls
        if row.command == "summary":
            done = regenerate_summary(platform, ref, live, cfg, llm, ctx.settings, trace)
            body = render_actions(st.author, [SUMMARY_DONE if done else SUMMARY_SKIPPED])
        elif row.command == "create_issue":
            from app.merge.create_issue import create_issue_from_chat

            identity = bot_identity(ctx.settings, ref.provider, inst.gitlab_bot_username)
            body = create_issue_from_chat(
                platform, ref, live, row, parse_comment(row.body, identity).text, cfg, llm,
                ctx.settings, trace,
            )  # fmt: skip
        else:
            identity = bot_identity(ctx.settings, ref.provider, inst.gitlab_bot_username)
            question = _question(row, parse_comment(row.body, identity).text)
            meta = row.meta or {}
            finding = _finding(s, pr.id, row.thread_ref)
            path = meta.get("path") or (finding.path if finding else None)
            line = meta.get("line") or (finding.end_line if finding else None)
            learnings = _learnings(knowledge, question, path, ctx.settings, trace)
            comments = _comments(platform, ref, pr.number)
            c = ChatContext(
                author=st.author,
                question=question,
                pr_ref=f"{repo.full_name}#{pr.number}",
                pr_title=live.title,
                pr_body=live.body,
                thread=_thread(comments, row, ctx.settings.chat_thread_max_messages),
                path=path,
                line=line,
                diff_hunk=meta.get("diff_hunk"),
                finding=(
                    f"{finding.title}\n\n{finding.body}"[:FINDING_MAX_CHARS] if finding else None
                ),
                walkthrough=_walkthrough(comments),
                learnings=tuple(learnings),
                request=SEQUENCE_DIAGRAM_REQUEST if row.command == "sequence_diagram" else None,
            )
            st.lazy = LazySandbox(
                ctx.sandboxes,
                f"chat-{row.id}",
                _creds(platform, ref, st),
                live.head_sha,
                ctx.settings,
            )
            allow_shell = ctx.settings.sandbox_backend == "docker"
            limits = AgentLimits(
                ctx.settings.chat_agent_max_steps,
                ctx.settings.chat_max_input_tokens,
                ctx.settings.agent_shell_timeout_s,
                ctx.settings.agent_shell_max_output_kb,
                allow_shell=allow_shell,
            )
            toolbox = Toolbox(
                st.lazy, CodeGraph.empty(), ToolResults(), limits, external=st.external
            )
            # Only commenters with write access may teach (they are stored org/repo-wide).
            can_teach = not opted_out and meta.get("can_write") is True
            add = None if not can_teach else _adder(ctx, llm, org.id, repo.id, pr, row, trace)
            outcome = run_chat_agent(
                llm,
                c,
                cfg,
                ctx.settings,
                toolbox=toolbox,
                allow_shell=allow_shell,
                add_learning=add,
                trace=trace,
            )
            answer = harden_answer(
                outcome.answer, st.author, ref.provider, ctx.settings, st.secrets
            )
            location = f"{path}:{line}" if path and line else path
            body = render_chat_reply(
                st.author,
                answer,
                outcome.added,
                learnings,
                pr_ref=c.pr_ref,
                location=location,
                now=datetime.now(UTC),
            )
            log.info(
                "chat_answered",
                steps=outcome.steps,
                stop_reason=outcome.stop_reason,
                learnings_added=len(outcome.added),
                learnings_used=len(learnings),
                sandbox=st.lazy.created,
            )
        s.commit()
        row = s.get(ChatMessage, chat_id, populate_existing=True)
        if row is None:
            raise ChatAborted("the chat message is gone")
        rid = post_reply(platform, ref, pr.number, row, body)
        st.delivered = True
        _complete(ctx, s, chat_id, rid, llm)
    except Exception as exc:
        s.rollback()
        log.warning("chat_failed", error=f"{type(exc).__name__}: {exc}"[:300], exc_info=True)
        _fail(ctx, s, chat_id, exc, llm, charge=st.delivered)
        if st.platform is not None and st.ref is not None and not st.delivered and st.author:
            try:
                row = s.get(ChatMessage, chat_id)
                if row is not None:
                    post_reply(st.platform, st.ref, st.number, row, render_chat_error(st.author))
            except Exception:
                log.warning("chat_error_reply_failed", exc_info=True)
    finally:
        if st.external is not None:
            st.external.close()
        if st.lazy is not None:
            try:
                st.lazy.destroy()
            except Exception:
                log.warning("chat_sandbox_destroy_failed", exc_info=True)
        if st.platform is not None:
            close_platform(st.platform)


# --- context ------------------------------------------------------------------------------


def _question(row: ChatMessage, text: str) -> str:
    """The developer's words without the mention (and without the command phrase)."""
    q = text or row.body
    if row.command == "sequence_diagram":
        lowered = q.lower()
        phrase = "generate sequence diagram"
        if lowered.startswith(phrase):
            q = q[len(phrase) :]
    return q.strip()


def _finding(s: Session, pr_id: UUID, thread_ref: str | None) -> Finding | None:
    if not thread_ref:
        return None
    return s.execute(
        select(Finding)
        .join(Review, Review.id == Finding.review_id)
        .where(
            Review.pr_id == pr_id,
            Finding.posted.is_(True),
            Finding.provider_comment_id == thread_ref,
        )
        .order_by(Finding.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _comments(platform: GitPlatform, ref: RepoRef, number: int) -> list[Comment]:
    try:
        return platform.list_comments(ref, number)
    except Exception:  # context only: answer without the thread history
        log.warning("chat_list_comments_failed", exc_info=True)
        return []


def _thread(
    comments: Sequence[Comment], row: ChatMessage, limit: int
) -> tuple[tuple[str, str], ...]:
    """Earlier messages of the comment's thread (oldest first, last ``limit``)."""
    if not row.thread_ref or limit <= 0:
        return ()
    items = [
        c
        for c in comments
        if (c.thread_ref == row.thread_ref or c.id == row.thread_ref)
        and c.id != row.provider_comment_id
        and c.id != row.reply_comment_id
    ]
    epoch = datetime.min.replace(tzinfo=UTC)
    items.sort(key=lambda c: c.created_at or epoch)
    return tuple((c.author_username, c.body) for c in items[-limit:])


def _walkthrough(comments: Sequence[Comment]) -> str:
    for c in comments:
        if WALKTHROUGH_MARKER in c.body:
            return c.body.replace(WALKTHROUGH_MARKER, "").strip()
    return ""


def _learnings(
    kb: KnowledgeBase, question: str, path: str | None, settings: Settings, trace: TraceContext
) -> list[LearningHit]:
    try:
        return kb.learnings_for(
            f"{question} {path or ''}".strip(),
            [path] if path else [],
            k=settings.learnings_top_k,
            trace=trace,
        )
    except Exception:  # embeddings down: answer without learnings
        log.warning("chat_learnings_failed", exc_info=True)
        return []


def _creds(platform: GitPlatform, ref: RepoRef, st: _Run) -> Callable[[], CloneCredentials]:
    def get() -> CloneCredentials:
        creds = platform.clone_credentials(ref)
        if creds.token:
            st.secrets.append(creds.token)
        return creds

    return get


def _adder(
    ctx: WorkerContext,
    embedder: Embedder,
    org_id: UUID,
    repo_id: UUID,
    pr: PullRequest,
    row: ChatMessage,
    trace: TraceContext,
) -> AddLearningFn:
    source_url = (row.meta or {}).get("url") or pr.url or None
    number, author, row_id = pr.number, row.author_username, row.id

    def add(text: str, scope: Literal["repo", "org"], glob: str | None) -> AddedLearning:
        with ctx.session_factory() as s2:
            added = add_learning(
                s2,
                embedder,
                ctx.settings,
                org_id=org_id,
                repo_id=repo_id,
                text=text,
                scope=scope,
                path_glob=glob,
                source_url=source_url,
                pr_number=number,
                author=author,
                chat_message_id=row_id,
                trace=trace,
            )
            s2.commit()
        log.info("learning_added", learning_id=added.id, scope=scope)
        return added

    return add


# --- output -------------------------------------------------------------------------------


def harden_answer(
    text: str, author: str, provider: str, settings: Settings, secrets: Sequence[str] = ()
) -> str:
    """Model answer -> postable text: credentials redacted (incl. the live clone token), links
    outside the repository host / docs allowlist removed, nobody but the asker pinged, no raw
    HTML, no GitLab quick actions, capped at ``CHAT_REPLY_MAX_CHARS``. Code fences (Mermaid)
    are kept."""
    for secret in secrets:
        if len(secret) >= 4:
            text = text.replace(secret, "[REDACTED token]")
    text = redact_secrets(text)
    host = repo_host(provider, settings)
    text = scrub_urls(text, frozenset({"github.com", "gitlab.com", host}))
    return harden_text(
        text, settings.chat_reply_max_chars, allow_mentions=frozenset({author.lower()})
    )


# --- bookkeeping --------------------------------------------------------------------------


def _usage(row: ChatMessage, llm: MeteredLLM | None) -> None:
    if llm is None:
        return
    row.input_tokens = llm.usage.input_tokens
    row.output_tokens = llm.usage.output_tokens
    row.cost_usd = llm.cost_usd


def _complete(
    ctx: WorkerContext, s: Session, chat_id: UUID, reply_id: str, llm: MeteredLLM | None
) -> None:
    row = s.get(ChatMessage, chat_id, with_for_update=True, populate_existing=True)
    if row is None:  # pragma: no cover - the row cannot vanish while we hold the job
        return
    hold = ctx.ledger.find_open_reservation(s, CHAT_REF_TYPE, chat_id)
    if hold is not None:
        actual = llm.credits if llm is not None else hold.amount
        row.credits_charged = ctx.ledger.settle(
            s, hold, actual, ctx.settings.chat_min_charge, final_reason="chat"
        )
    _usage(row, llm)
    row.reply_comment_id = reply_id
    row.status, row.error, row.finished_at = "completed", None, utcnow()
    s.commit()


def _fail(
    ctx: WorkerContext,
    s: Session,
    chat_id: UUID,
    exc: Exception,
    llm: MeteredLLM | None,
    *,
    charge: bool,
) -> None:
    """Failure bookkeeping; the hold is released unless the answer already reached the PR."""
    try:
        row = s.get(ChatMessage, chat_id, with_for_update=True, populate_existing=True)
        if row is None:
            return
        hold = ctx.ledger.find_open_reservation(s, CHAT_REF_TYPE, chat_id)
        if hold is not None:
            if charge:
                actual = llm.credits if llm is not None else hold.amount
                row.credits_charged = ctx.ledger.settle(
                    s, hold, actual, ctx.settings.chat_min_charge, final_reason="chat"
                )
            else:
                ctx.ledger.release(s, hold)
                row.credits_charged = Decimal(0)
        _usage(row, llm)
        row.status = "completed" if charge else "failed"
        row.error = f"{type(exc).__name__}: {exc}"[:2000]
        row.finished_at = utcnow()
        s.commit()
    except Exception:
        s.rollback()
        log.exception("chat_fail_bookkeeping_failed")


# --- maintenance --------------------------------------------------------------------------


def sweep_stuck_chats(ctx: WorkerContext, *, now: datetime | None = None) -> int:
    """Beat task: fail + refund chats stuck in ``queued``/``running`` past
    ``CHAT_STUCK_TIMEOUT_MINUTES`` (lost broker message, dead worker), like
    ``sweep_stuck_reviews``; the asker gets the "no credit was charged" reply (best effort)."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=ctx.settings.chat_stuck_timeout_minutes)
    with ctx.session_factory() as s:
        ids = list(
            s.execute(
                select(ChatMessage.id).where(
                    ChatMessage.status.in_(("queued", "running")),
                    ChatMessage.updated_at < cutoff,
                )
            ).scalars()
        )
        s.rollback()
        n = 0
        for chat_id in ids:
            row = s.get(ChatMessage, chat_id, with_for_update=True, populate_existing=True)
            if row is None or row.status not in ("queued", "running") or row.updated_at >= cutoff:
                s.rollback()
                continue
            hold = ctx.ledger.find_open_reservation(s, CHAT_REF_TYPE, chat_id)
            if hold is not None:
                ctx.ledger.release(s, hold)
            row.credits_charged = Decimal(0)
            row.status, row.finished_at = "failed", utcnow()
            row.error = "Timeout: the chat job was lost or timed out before it finished"
            s.commit()
            n += 1
            log.warning("chat_stuck_failed", chat_id=str(chat_id))
            _post_stuck_error(ctx, s, chat_id)
        return n


def _post_stuck_error(ctx: WorkerContext, s: Session, chat_id: UUID) -> None:
    row = s.get(ChatMessage, chat_id)
    pr = s.get(PullRequest, row.pr_id) if row is not None else None
    repo = s.get(Repository, pr.repo_id) if pr is not None else None
    if row is None or pr is None or repo is None:
        return
    platform: GitPlatform | None = None
    try:
        platform = ctx.platforms(s, repo)
        post_reply(platform, repo_ref(repo), pr.number, row, render_chat_error(row.author_username))
    except Exception:
        log.warning("chat_stuck_reply_failed", exc_info=True)
    finally:
        if platform is not None:
            close_platform(platform)
