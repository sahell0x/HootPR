"""``change_stack.chat``: answer one pinned Change Stack chat question (spec §10.5).

Same chat agent as PR threads (phase 3) and the same billing: the API took a ``chat``
rate-limit slot and held up to ``CHAT_HOLD_MAX`` (ref ``change_stack_chat`` / the assistant row
id). The hold is settled at the metered credits when the answer is stored and released on any
failure. The answer lives only in the dashboard; nothing is posted to the pull request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.change_stack.workspace import hunk_text
from app.chat.agent import ChatContext, run_chat_agent
from app.chat.run import harden_answer
from app.chat.sandbox import LazySandbox
from app.config.loader import load_effective_config
from app.knowledge.learnings import SqlKnowledge
from app.llm.types import TraceContext
from app.logging import get_logger
from app.models import ChangeStackMessage, Finding, PullRequest, Repository, Review
from app.models.base import utcnow
from app.platforms.base import CloneCredentials, FileDiff, GitPlatform
from app.platforms.factory import close_platform, repo_ref
from app.review.agent import AgentLimits, Toolbox
from app.review.graph import CodeGraph
from app.review.llm import MeteredLLM
from app.review.pipeline import find_reviewable_repo, resolve_knowledge
from app.review.tool_results import ToolResults
from app.worker.context import WorkerContext

log = get_logger(__name__)
CS_CHAT_REF_TYPE = "change_stack_chat"
HISTORY_MESSAGES = 10
FINDING_MAX_CHARS = 3000
STUCK_AFTER = timedelta(minutes=30)


def _history(s: Session, pr_id: UUID, before: datetime) -> tuple[tuple[str, str], ...]:
    rows = list(
        s.execute(
            select(ChangeStackMessage)
            .where(
                ChangeStackMessage.pr_id == pr_id,
                ChangeStackMessage.created_at < before,
                ChangeStackMessage.status == "completed",
            )
            .order_by(ChangeStackMessage.created_at.desc())
            .limit(HISTORY_MESSAGES)
        ).scalars()
    )
    rows.reverse()
    return tuple(("hootpr" if r.role == "assistant" else "developer", r.body) for r in rows)


def _finding_at(s: Session, pr_id: UUID, path: str | None, line: int | None) -> str | None:
    if not path:
        return None
    q = (
        select(Finding)
        .join(Review, Review.id == Finding.review_id)
        .where(Review.pr_id == pr_id, Finding.path == path, Finding.posted.is_(True))
        .order_by(Finding.created_at.desc())
        .limit(20)
    )
    for f in s.execute(q).scalars():
        lo = f.start_line or f.end_line
        if line is None or lo - 3 <= line <= f.end_line + 3:
            return f"{f.title}\n\n{f.body}"[:FINDING_MAX_CHARS]
    return None


def run_change_stack_chat(ctx: WorkerContext, answer_id: UUID) -> str:
    with ctx.session_factory() as s:
        ans = s.get(ChangeStackMessage, answer_id, with_for_update=True)
        if ans is None or ans.status != "queued":
            return "skipped"
        ans.status = "running"
        s.commit()
        platform: GitPlatform | None = None
        lazy: LazySandbox | None = None
        llm: MeteredLLM | None = None
        secrets: list[str] = []
        try:
            ans = s.get(ChangeStackMessage, answer_id)
            q = s.get(ChangeStackMessage, ans.question_id) if ans and ans.question_id else None
            pr = s.get(PullRequest, ans.pr_id) if ans is not None else None
            repo = s.get(Repository, pr.repo_id) if pr is not None else None
            if ans is None or q is None or pr is None or repo is None:
                raise RuntimeError("the question or pull request is gone")
            found = find_reviewable_repo(s, repo.provider, repo.provider_repo_id)
            if found is None:
                raise RuntimeError("the repository is no longer enabled")
            _, org, _inst = found
            ref = repo_ref(repo)
            platform = ctx.platforms(s, repo)
            live = platform.get_pull_request(ref, pr.number)
            resolved = load_effective_config(
                platform, ref, live.base_ref or repo.default_branch, repo.settings, org.settings
            )
            cfg, knowledge = resolve_knowledge(ctx, s, resolved.config, org, repo)
            llm = MeteredLLM(ctx.llm())
            if isinstance(knowledge, SqlKnowledge):
                knowledge = knowledge.bind_embedder(llm)
            trace = TraceContext(org_id=org.id, chat_id=ans.id, stage="chat")
            diff: list[FileDiff] = []
            if q.path:
                try:
                    diff = platform.get_diff(ref, pr.number)
                except Exception:
                    log.warning("cs_chat_diff_failed", exc_info=True)
            learnings = []
            try:
                learnings = knowledge.learnings_for(
                    f"{q.body} {q.path or ''}".strip(),
                    [q.path] if q.path else [],
                    k=ctx.settings.learnings_top_k,
                    trace=trace,
                )
            except Exception:
                log.warning("cs_chat_learnings_failed", exc_info=True)
            author = "developer"
            c = ChatContext(
                author=author,
                question=q.body,
                pr_ref=f"{repo.full_name}#{pr.number}",
                pr_title=live.title,
                pr_body=live.body,
                thread=_history(s, pr.id, q.created_at),
                path=q.path,
                line=q.line,
                diff_hunk=hunk_text(diff, q.path, q.line) if q.path else None,
                finding=_finding_at(s, pr.id, q.path, q.line),
                walkthrough="",
                learnings=tuple(learnings),
            )
            s.commit()  # nothing stays locked during LLM calls

            def creds() -> CloneCredentials:
                if platform is None:
                    raise RuntimeError("platform closed")
                cr = platform.clone_credentials(ref)
                if cr.token:
                    secrets.append(cr.token)
                return cr

            lazy = LazySandbox(ctx.sandboxes, f"cs-{ans.id}", creds, live.head_sha, ctx.settings)
            allow_shell = ctx.settings.sandbox_backend == "docker"
            limits = AgentLimits(
                ctx.settings.chat_agent_max_steps,
                ctx.settings.chat_max_input_tokens,
                ctx.settings.agent_shell_timeout_s,
                ctx.settings.agent_shell_max_output_kb,
                allow_shell=allow_shell,
            )
            toolbox = Toolbox(lazy, CodeGraph.empty(), ToolResults(), limits)
            outcome = run_chat_agent(
                llm,
                c,
                cfg,
                ctx.settings,
                toolbox=toolbox,
                allow_shell=allow_shell,
                add_learning=None,
                trace=trace,
            )
            answer = harden_answer(outcome.answer, author, ref.provider, ctx.settings, secrets)
            _finish(ctx, s, answer_id, answer, llm, ok=True)
            return "completed"
        except Exception as exc:
            s.rollback()
            log.warning("cs_chat_failed", error=f"{type(exc).__name__}: {exc}"[:300])
            _finish(ctx, s, answer_id, None, llm, ok=False, error=exc)
            return "failed"
        finally:
            if lazy is not None:
                try:
                    lazy.destroy()
                except Exception:
                    log.warning("cs_chat_sandbox_destroy_failed", exc_info=True)
            if platform is not None:
                close_platform(platform)


def _finish(
    ctx: WorkerContext,
    s: Session,
    answer_id: UUID,
    answer: str | None,
    llm: MeteredLLM | None,
    *,
    ok: bool,
    error: Exception | None = None,
) -> None:
    try:
        row = s.get(ChangeStackMessage, answer_id, with_for_update=True, populate_existing=True)
        if row is None:
            return
        hold = ctx.ledger.find_open_reservation(s, CS_CHAT_REF_TYPE, answer_id)
        if hold is not None:
            if ok:
                actual = llm.credits if llm is not None else hold.amount
                row.credits_charged = ctx.ledger.settle(
                    s, hold, actual, ctx.settings.chat_min_charge, final_reason="chat"
                )
            else:
                ctx.ledger.release(s, hold)
                row.credits_charged = Decimal(0)
        if llm is not None:
            row.input_tokens = llm.usage.input_tokens
            row.output_tokens = llm.usage.output_tokens
            row.cost_usd = llm.cost_usd
        if ok:
            row.body, row.status, row.error = answer or "", "completed", None
        else:
            row.body = "HootPR hit an error while answering this. No credit was charged."
            row.status = "failed"
            row.error = f"{type(error).__name__}: {error}"[:2000] if error else None
        row.finished_at = utcnow()
        s.commit()
    except Exception:
        s.rollback()
        log.exception("cs_chat_bookkeeping_failed")


def sweep_stuck(ctx: WorkerContext, *, now: datetime | None = None) -> int:
    """Fail + refund answers stuck in queued/running (lost job) past ``STUCK_AFTER``."""
    now = now or datetime.now(UTC)
    n = 0
    with ctx.session_factory() as s:
        ids = list(
            s.execute(
                select(ChangeStackMessage.id).where(
                    ChangeStackMessage.role == "assistant",
                    ChangeStackMessage.status.in_(("queued", "running")),
                    ChangeStackMessage.updated_at < now - STUCK_AFTER,
                )
            ).scalars()
        )
        s.rollback()
        for mid in ids:
            _finish(ctx, s, mid, None, None, ok=False, error=TimeoutError("chat job was lost"))
            n += 1
    return n
