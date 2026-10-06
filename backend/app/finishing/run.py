"""``finishing.run``: execute one finishing-touch job (spec §10.1).

Code-changing kinds: sandbox clone (PR head + base branch, sealed) → optional dependency install
(network on, then re-sealed) → code-change agent → tests (≤ ``FINISHING_MAX_TEST_ITERATIONS``
rounds, failures fed back) → change set → push from the worker (commit on the PR branch or a
stacked PR/MR). ``ci_analysis`` only reads CI logs and comments (see ``ci.py``).

Billing: the hold taken by the command handler is committed only when something was delivered;
"no changes", failures and crashes release it. The sandbox is always destroyed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.actions import post_reply
from app.config.loader import load_effective_config
from app.config.schema import HootPRConfig
from app.finishing.agent import CodeAgentLimits, CodeChangeAgent
from app.finishing.commands import Delivery, Kind, find_recipe
from app.finishing.handler import FINISHING_REF_TYPE
from app.finishing.prompts import TaskContext, task_prompt
from app.finishing.repair import (
    MarkerRepairContext,
    TestRepairContext,
    repair_conflict_markers,
    repair_until_tests_pass,
)
from app.finishing.replies import (
    EMOJI,
    ResultView,
    label,
    render_failed,
    render_no_changes,
    render_result,
)
from app.finishing.workspace import (
    ChangeSetError,
    Project,
    StepResult,
    SuggestionEdit,
    apply_suggestions,
    collect_changes,
    configure_git,
    detect_project,
    git,
    install_dependencies,
    is_junk,
    parse_porcelain_z,
    resolve_base_tip,
    start_merge,
)
from app.knowledge.text import redact_secrets
from app.llm.types import TraceContext
from app.logging import get_logger
from app.models import ChatMessage, Finding, FinishingJob, PullRequest, Repository, Review
from app.models.base import utcnow
from app.platforms.base import FileDiff, GitPlatform, RepoRef
from app.platforms.base import PullRequest as LivePR
from app.platforms.factory import close_platform, repo_ref
from app.platforms.finishing import FileChange, PushRejected, branch_name
from app.review.context import path_instructions_for
from app.review.llm import MeteredLLM
from app.review.pipeline import find_reviewable_repo
from app.review.safety import clean_prose, repo_host
from app.review.stages.diff_filter import glob_match
from app.sandbox.base import Sandbox
from app.settings import Settings
from app.worker.context import WorkerContext

log = get_logger(__name__)
TEST_KINDS: frozenset[str] = frozenset(
    {"unit_tests", "autofix", "simplify", "fix_ci", "merge_conflict", "custom"}
)
DIFF_MAX_CHARS = 40_000
SUMMARY_MAX_CHARS = 3000
MAX_MARKER_ROUNDS = 2
TITLES: dict[Kind, str] = {
    "docstrings": "📝 Add docstrings to `{head}`",
    "unit_tests": "🧪 Add unit tests for PR #{number}",
    "autofix": "🔧 Apply HootPR review suggestions",
    "simplify": "♻️ Simplify code in PR #{number}",
    "fix_ci": "💚 Fix CI failures on `{head}`",
    "merge_conflict": "🔀 Merge `{base}` into `{head}` and resolve conflicts",
    "custom": "✨ {recipe} for PR #{number}",
    "ci_analysis": "CI failure analysis",
}


class FinishingAborted(Exception):
    """The job cannot run (repository gone/disabled, PR closed, worker crash)."""


class NothingToDo(Exception):
    """Nothing to change; the message is shown to the requester."""


class FinishingFailed(Exception):
    """A user-facing failure (push rejected, markers left, change set too large)."""


@dataclass
class ChangeOutcome:
    changes: list[FileChange]
    summary: str
    verification: str
    detail: str
    test_command: str | None
    tree_base: str
    extra_parents: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


@dataclass
class _State:
    platform: GitPlatform | None = None
    ref: RepoRef | None = None
    number: int = 0
    author: str = ""
    kind: Kind = "docstrings"
    recipe: str | None = None
    trigger: str = "command"
    chat_id: UUID | None = None
    sb: Sandbox | None = None
    secrets: list[str] = field(default_factory=list)
    delivered: bool = False


def run_finishing(ctx: WorkerContext, job_id: UUID) -> None:
    """Celery ``finishing.run``. A ``running`` row means the worker died mid-job (acks_late
    redelivery): it is failed and refunded, never run twice."""
    with (
        structlog.contextvars.bound_contextvars(finishing_job_id=str(job_id)),
        ctx.session_factory() as s,
    ):
        job = s.get(FinishingJob, job_id, with_for_update=True)
        if job is None or job.status not in ("queued", "running"):
            return
        crashed = job.status == "running"
        job.status = "running"
        job.started_at = job.started_at or utcnow()
        s.commit()
        _run(ctx, s, job_id, crashed)


def _run(ctx: WorkerContext, s: Session, job_id: UUID, crashed: bool) -> None:
    st = _State()
    llm: MeteredLLM | None = None
    try:
        job = s.get(FinishingJob, job_id)
        pr = s.get(PullRequest, job.pr_id) if job is not None else None
        repo = s.get(Repository, pr.repo_id) if pr is not None else None
        if job is None or pr is None or repo is None:
            raise FinishingAborted("the pull request is gone")
        st.number, st.author, st.chat_id = pr.number, job.requested_by, job.chat_message_id
        st.kind, st.recipe, st.trigger = cast(Kind, job.kind), job.recipe_name, job.trigger
        found = find_reviewable_repo(s, repo.provider, repo.provider_repo_id)
        if found is None:
            raise FinishingAborted("the repository is no longer enabled")
        _, org, inst = found
        st.ref = repo_ref(repo)
        st.platform = ctx.platforms(s, repo)
        if crashed:
            raise FinishingAborted("the worker stopped while working on it")
        platform, ref = st.platform, st.ref
        live = platform.get_pull_request(ref, pr.number)
        if live.state != "open":
            raise FinishingAborted("the pull request is not open")
        resolved = load_effective_config(
            platform, ref, live.base_ref or repo.default_branch, repo.settings, org.settings
        )
        cfg = resolved.config
        llm = MeteredLLM(ctx.llm())
        stage = "chat" if st.kind == "ci_analysis" else "finishing"
        # ``task_id`` attributes the calls to the job (its credit receipt).
        trace = TraceContext(
            org_id=org.id, chat_id=job.chat_message_id, task_id=job_id, stage=stage
        )
        delivery = cast(Delivery, job.delivery)
        meta = dict(job.meta or {})
        s.commit()  # nothing stays locked during sandbox/LLM work
        if st.kind == "ci_analysis":
            from app.finishing.ci import run_ci_analysis

            run_ci_analysis(ctx, platform, ref, live, cfg, llm, trace, inst.gitlab_bot_username)
            st.delivered = True
            _complete(ctx, s, job_id, llm, updates={"delivery": "comment"}, final_reason="chat")
            return
        outcome = _code_change(ctx, s, st, job_id, pr.id, live, cfg, llm, trace, meta)
        if not outcome.changes and not outcome.extra_parents:
            raise NothingToDo(outcome.summary.strip() or "HootPR found nothing to change.")
        _deliver(ctx, s, st, job_id, live, delivery, outcome, llm)
    except NothingToDo as exc:
        s.rollback()
        reason = _harden(str(exc), st, ctx.settings)
        _fail(ctx, s, job_id, llm, status="no_changes", error=reason)
        _reply(ctx, s, st, render_no_changes(st.author, st.kind, st.recipe, reason))
    except Exception as exc:
        s.rollback()
        log.warning("finishing_failed", error=f"{type(exc).__name__}: {exc}"[:300], exc_info=True)
        user_msg = (
            _harden(str(exc), st, ctx.settings)
            if isinstance(exc, FinishingAborted | FinishingFailed)
            else "HootPR hit an internal error."
        )
        _fail(ctx, s, job_id, llm, status="failed", error=f"{type(exc).__name__}: {exc}")
        if not st.delivered:
            _reply(ctx, s, st, render_failed(st.author, st.kind, st.recipe, user_msg))
    finally:
        if st.sb is not None:
            try:
                st.sb.destroy()
            except Exception:
                log.warning("finishing_sandbox_destroy_failed", exc_info=True)
        if st.platform is not None:
            close_platform(st.platform)


# --- the code change ------------------------------------------------------------------------


def _diff_context(platform: GitPlatform, ref: RepoRef, number: int) -> tuple[list[str], str]:
    try:
        diffs: list[FileDiff] = platform.get_diff(ref, number)
    except Exception:
        log.warning("finishing_diff_failed", exc_info=True)
        return [], ""
    files = [d.path for d in diffs if d.status != "removed"]
    parts: list[str] = []
    size = 0
    for d in diffs:
        if d.is_binary or not d.patch:
            continue
        chunk = f"### {d.path}\n{d.patch}\n"
        if size + len(chunk) > DIFF_MAX_CHARS:
            parts.append(f"### {d.path}\n[diff omitted: size budget]\n")
            continue
        parts.append(chunk)
        size += len(chunk)
    return files, "".join(parts)


def _open_findings(s: Session, pr_id: UUID) -> list[tuple[Finding, str]]:
    rows = s.execute(
        select(Finding, Review.head_sha)
        .join(Review, Review.id == Finding.review_id)
        .where(Review.pr_id == pr_id, Finding.posted.is_(True), Finding.status == "open")
        .order_by(Finding.path, Finding.end_line)
    ).all()
    return [(f, sha) for f, sha in rows]


def _render_findings(items: list[tuple[Finding, str]], applied: set[str]) -> str:
    out: list[str] = []
    for f, _ in items:
        lines = f"{f.start_line}-{f.end_line}" if f.start_line else str(f.end_line)
        state = "applied" if str(f.id) in applied else "to fix"
        block = f"- [{state}] {f.path}:{lines} ({f.severity}) {f.title}\n  {f.body[:1500]}"
        if f.suggestion is not None and state == "to fix":
            block += f"\n  Suggested replacement for those lines:\n```\n{f.suggestion[:2000]}\n```"
        out.append(block)
    return "\n".join(out)


def _has_changes(sb: Sandbox) -> bool:
    r = git(sb, "status", "--porcelain=v1", "-z", "--untracked-files=all", max_kb=512)
    return any(not (xy == "??" and is_junk(p)) for xy, p in parse_porcelain_z(r.stdout))


def _code_change(
    ctx: WorkerContext,
    s: Session,
    st: _State,
    job_id: UUID,
    pr_id: UUID,
    live: LivePR,
    cfg: HootPRConfig,
    llm: MeteredLLM,
    trace: TraceContext,
    meta: dict[str, object],
) -> ChangeOutcome:
    settings = ctx.settings
    if st.platform is None or st.ref is None:  # pragma: no cover - set before any work
        raise FinishingAborted("the platform is not available")
    platform, ref, kind = st.platform, st.ref, st.kind
    files, diff = _diff_context(platform, ref, live.number)
    task = TaskContext(
        pr_ref=f"{ref.full_name}#{live.number}",
        title=live.title,
        head_ref=live.head_ref,
        base_ref=live.base_ref,
        files=files,
        diff=diff,
        language=cfg.code_generation.docstrings.language,
    )
    notes: list[str] = []
    path_notes: list[str] = []
    for path in files:
        path_notes += [f"{path}: {n}" for n in path_instructions_for(path, cfg)]
        gen = (
            cfg.code_generation.docstrings.path_instructions
            if kind == "docstrings"
            else cfg.code_generation.unit_tests.path_instructions
            if kind == "unit_tests"
            else []
        )
        path_notes += [f"{path}: {p.instructions}" for p in gen if glob_match(path, p.path)]
    task.path_notes = path_notes[:30]

    # Work that needs no sandbox first: cheap "nothing to do" exits.
    findings: list[tuple[Finding, str]] = []
    if kind == "autofix":
        findings = _open_findings(s, pr_id)
        s.commit()
        if not findings:
            raise NothingToDo("there are no open HootPR review comments on this pull request.")
    if kind == "fix_ci":
        run_id = meta.get("run_id")
        logs = platform.get_ci_logs(
            ref,
            live.head_sha,
            run_id=str(run_id) if run_id else None,
            max_jobs=settings.ci_log_max_jobs,
            max_log_kb=settings.ci_log_max_kb,
        )
        if not logs:
            raise NothingToDo("no failed CI jobs were found for the latest commit.")
        task.ci_logs = "\n\n".join(
            f"## Job: {j.name} (run {j.run_name or j.run_id}, step: {j.failed_step or '-'})\n"
            f"{j.log_tail}"
            for j in logs
        )
    if kind == "custom":
        recipe = find_recipe(cfg, st.recipe or "")
        if recipe is None or not recipe.enabled:
            raise FinishingFailed(f"the recipe `{st.recipe}` is no longer configured.")
        task.recipe, task.instructions = recipe.name, recipe.instructions

    # Sandbox: PR head + base branch, sealed before anything else runs.
    mem = settings.sandbox_test_mem_mb if kind in TEST_KINDS else settings.sandbox_mem_mb
    sb = ctx.sandboxes.create(f"ft-{job_id}", mem_mb=mem, cpus=settings.sandbox_cpus)
    st.sb = sb
    creds = platform.clone_credentials(ref)
    if creds.token:
        st.secrets.append(creds.token)
    extra = [x for x in (live.base_sha,) if x] + [f"refs/heads/{live.base_ref}"]
    sb.clone(creds, live.head_sha, settings.finishing_clone_depth, extra_refs=extra)
    sb.seal()
    configure_git(sb)
    allow_shell = settings.sandbox_backend == "docker"
    project = detect_project(sb) if kind in TEST_KINDS else Project()
    task.test_command = project.test if allow_shell else None
    install = StepResult("skipped")
    if kind in TEST_KINDS and project.test and allow_shell:
        install = install_dependencies(sb, project, settings.finishing_test_timeout_s)
        log.info("finishing_install", status=install.status)

    extra_parents: tuple[str, ...] = ()
    conflicted: tuple[str, ...] = ()
    need_agent = True
    if kind == "autofix":
        edits = [
            SuggestionEdit(f.path, f.start_line or f.end_line, f.end_line, f.suggestion, str(f.id))
            for f, _ in findings
            if f.suggestion is not None and f.side == "RIGHT"
        ]
        anchors = {str(f.id): sha for f, sha in findings}
        report = apply_suggestions(sb, edits, anchors, settings.finishing_max_file_kb)
        applied = set(report.applied)
        if applied:
            notes.append(f"Applied {len(applied)} HootPR suggestion(s) as written.")
        task.findings = _render_findings(findings, applied)
        need_agent = any(str(f.id) not in applied for f, _ in findings)
    if kind == "merge_conflict":
        tip = resolve_base_tip(sb, live.base_ref)
        if tip is None:
            raise FinishingFailed(f"HootPR could not fetch the base branch `{live.base_ref}`.")
        state = start_merge(sb, tip)
        if state.clean:
            raise NothingToDo(f"`{live.head_ref}` merges cleanly into `{live.base_ref}`.")
        if state.error:
            raise FinishingFailed(f"the merge could not be started ({state.error[:200]}).")
        conflicted, extra_parents = state.conflicted, (tip,)
        task.conflicted = conflicted

    agent = CodeChangeAgent(
        llm,
        sb,
        cfg,
        CodeAgentLimits(
            settings.finishing_agent_max_steps,
            settings.finishing_max_input_tokens,
            settings.finishing_max_total_input_tokens,
            allow_shell,
        ),
        trace,
    )
    summary = ""
    if need_agent:
        rnd = agent.start(task_prompt(kind, task))
        summary = rnd.summary
        log.info("finishing_agent_round", steps=rnd.steps, edits=rnd.edits, stop=rnd.stop_reason)
    if conflicted:
        left, summary = repair_conflict_markers(
            MarkerRepairContext(sb, agent, conflicted, MAX_MARKER_ROUNDS), summary
        )
        if left:
            raise FinishingFailed("conflict markers remain in " + ", ".join(left[:10]) + ".")

    verification, detail = "not_run", ""
    if kind in TEST_KINDS and allow_shell and not project.test and _has_changes(sb):
        # The repo had no tests before; the agent may have just written its first ones.
        project = detect_project(sb)
        task.test_command = project.test
        if project.test:
            install = install_dependencies(sb, project, settings.finishing_test_timeout_s)
            log.info("finishing_install", status=install.status, redetected=True)
    if kind in TEST_KINDS and _has_changes(sb):
        verification, detail, summary = _verify(
            ctx, sb, agent, project, install, allow_shell, summary
        )

    try:
        changes = collect_changes(
            sb,
            live.head_sha,
            max_files=settings.finishing_max_files,
            max_kb=settings.finishing_max_file_kb,
        )
        tree_base = live.head_sha
    except ChangeSetError:
        if not extra_parents:
            raise
        # A merge that brings many base-branch files: express it relative to the base tip.
        changes = collect_changes(
            sb,
            extra_parents[0],
            max_files=settings.finishing_max_files,
            max_kb=settings.finishing_max_file_kb,
        )
        tree_base = extra_parents[0]
    return ChangeOutcome(
        changes=changes,
        summary=summary,
        verification=verification,
        detail=detail,
        test_command=project.test,
        tree_base=tree_base,
        extra_parents=extra_parents,
        notes=notes,
    )


def _verify(
    ctx: WorkerContext,
    sb: Sandbox,
    agent: CodeChangeAgent,
    project: Project,
    install: StepResult,
    allow_shell: bool,
    summary: str,
) -> tuple[str, str, str]:
    """(verification, detail, summary). "couldn't verify" is reported, never hidden."""
    settings = ctx.settings
    if not allow_shell:
        return "couldnt_verify", "tests only run in the Docker sandbox", summary
    if not project.test:
        return (
            "couldnt_verify",
            "no test command was detected (pytest, a package.json `test` script or `go test`)",
            summary,
        )
    if install.status in ("failed", "timeout", "oom", "unavailable"):
        what = {"oom": "ran out of memory", "timeout": "timed out"}.get(install.status, "failed")
        return "couldnt_verify", f"installing dependencies {what}\n{install.detail}", summary
    return repair_until_tests_pass(
        TestRepairContext(
            sb,
            agent,
            project,
            settings.finishing_test_timeout_s,
            settings.finishing_max_test_iterations,
        ),
        summary,
    )


# --- delivery -------------------------------------------------------------------------------


def commit_url(provider: str, pr_url: str, sha: str) -> str | None:
    if not pr_url:
        return None
    if provider == "gitlab":
        return f"{pr_url}/diffs?commit_id={sha}"
    return f"{pr_url}/commits/{sha}"


def _title(kind: Kind, live: LivePR, recipe: str | None) -> str:
    return TITLES[kind].format(
        head=live.head_ref, base=live.base_ref, number=live.number, recipe=recipe or "Recipe"
    )


def _deliver(
    ctx: WorkerContext,
    s: Session,
    st: _State,
    job_id: UUID,
    live: LivePR,
    requested: Delivery,
    out: ChangeOutcome,
    llm: MeteredLLM,
) -> None:
    if st.platform is None or st.ref is None:  # pragma: no cover - set before any work
        raise FinishingAborted("the platform is not available")
    platform, ref, kind = st.platform, st.ref, st.kind
    summary = _harden(out.summary, st, ctx.settings)
    downgraded = out.verification == "failed" and requested == "commit"
    delivery: Delivery = "stacked_pr" if downgraded else requested
    title = _title(kind, live, st.recipe)
    message = (
        f"{title.replace('`', '')}\n\n{_plain(summary)}\n\n"
        f"Requested by @{st.author} on {ref.full_name}#{live.number}."
    )
    sha: str
    pr_number: int | None = None
    pr_url: str | None = None
    url: str | None = None
    try:
        if delivery == "commit":
            sha = platform.push_commit(
                ref,
                live.head_ref,
                live.head_sha,
                message,
                out.changes,
                extra_parents=out.extra_parents,
                tree_base=out.tree_base,
            )
            url = commit_url(ref.provider, live.url, sha)
        else:
            branch = branch_name(kind, live.number, str(job_id))
            sha = platform.push_commit(
                ref,
                branch,
                live.head_sha,
                message,
                out.changes,
                create_branch=True,
                extra_parents=out.extra_parents,
                tree_base=out.tree_base,
            )
            body = _stacked_body(st, live, summary, out)
            opened = platform.open_pull_request(ref, branch, live.head_ref, title, body)
            pr_number, pr_url = opened.number, opened.url
            url = opened.url
    except PushRejected as exc:
        raise FinishingFailed(
            f"the push was rejected — the branch `{live.head_ref}` probably moved while HootPR "
            "was working (or it lives in a fork HootPR cannot push to). Run the command again."
        ) from exc
    st.delivered = True
    view = ResultView(
        author=st.author,
        kind=kind,
        recipe=st.recipe,
        delivery=delivery,
        head_ref=live.head_ref,
        summary=summary,
        files=[c.path for c in out.changes],
        verification=out.verification,
        verification_detail=_harden(out.detail, st, ctx.settings, keep_code=True),
        test_command=out.test_command,
        sha=sha,
        commit_url=url if delivery == "commit" else None,
        pr_number=pr_number,
        pr_url=pr_url,
        downgraded=downgraded,
        notes=out.notes,
    )
    _complete(
        ctx,
        s,
        job_id,
        llm,
        updates={
            "delivery": delivery,
            "result_sha": sha,
            "result_pr_number": pr_number,
            "result_url": url,
            "verification": out.verification,
            "verification_detail": out.detail[-4000:] or None,
            "files_changed": len(out.changes),
            "summary": summary[:SUMMARY_MAX_CHARS] or None,
        },
    )
    _reply(ctx, s, st, render_result(view))


def _stacked_body(st: _State, live: LivePR, summary: str, out: ChangeOutcome) -> str:
    verification = {
        "verified": "✅ tests passed",
        "failed": "❌ tests failing — review before merging",
        "couldnt_verify": "⚠️ couldn't verify (tests not run)",
    }.get(out.verification, "not run")
    return "\n".join(
        [
            f"{EMOJI[st.kind]} **{label(st.kind, st.recipe)}** for [{live.title}]({live.url}), "
            f"requested by @{st.author}.",
            "",
            summary or "_No summary._",
            "",
            f"**Verification:** {verification}",
            "",
            f"Merge this pull request into `{live.head_ref}` to apply the changes.",
            "",
            "<sub>Generated by HootPR.</sub>",
        ]
    )


# --- helpers & bookkeeping -----------------------------------------------------------------


def _plain(text: str) -> str:
    return text.replace("​", "")[:SUMMARY_MAX_CHARS]


def _harden(text: str, st: _State, settings: Settings, *, keep_code: bool = False) -> str:
    for secret in st.secrets:
        if len(secret) >= 4:
            text = text.replace(secret, "[REDACTED token]")
    text = redact_secrets(text)
    if keep_code:
        return text
    provider = st.ref.provider if st.ref is not None else "github"
    return clean_prose(text, SUMMARY_MAX_CHARS, repo_host(provider, settings))


def _reply(ctx: WorkerContext, s: Session, st: _State, body: str) -> None:
    """Edit the command's acknowledgement (or reply in its thread); webhook-triggered jobs
    stay silent on failure."""
    if st.platform is None or st.ref is None:
        return
    try:
        row = s.get(ChatMessage, st.chat_id) if st.chat_id else None
        if row is not None:
            post_reply(st.platform, st.ref, st.number, row, body)
        elif st.trigger == "command":
            st.platform.upsert_comment(st.ref, st.number, "<!-- hootpr:finishing -->", body)
    except Exception:
        log.warning("finishing_reply_failed", exc_info=True)


def _usage(job: FinishingJob, llm: MeteredLLM | None) -> None:
    if llm is None:
        return
    job.input_tokens = llm.usage.input_tokens
    job.output_tokens = llm.usage.output_tokens
    job.cost_usd = llm.cost_usd


def _complete(
    ctx: WorkerContext,
    s: Session,
    job_id: UUID,
    llm: MeteredLLM | None,
    *,
    updates: dict[str, object],
    final_reason: str = "finishing",
) -> None:
    """Delivered: settle the hold at the metered credits (CI analysis bills like a chat reply)."""
    job = s.get(FinishingJob, job_id, with_for_update=True, populate_existing=True)
    if job is None:  # pragma: no cover
        return
    hold = ctx.ledger.find_open_reservation(s, FINISHING_REF_TYPE, job_id)
    if hold is not None:
        st = ctx.settings
        minimum = st.chat_min_charge if final_reason == "chat" else st.finishing_min_charge
        actual = llm.credits if llm is not None else hold.amount
        job.credits_charged = ctx.ledger.settle(s, hold, actual, minimum, final_reason=final_reason)
    for key, value in updates.items():
        setattr(job, key, value)
    _usage(job, llm)
    job.status, job.error, job.finished_at = "completed", None, utcnow()
    s.commit()


def _fail(
    ctx: WorkerContext,
    s: Session,
    job_id: UUID,
    llm: MeteredLLM | None,
    *,
    status: str,
    error: str,
) -> None:
    try:
        job = s.get(FinishingJob, job_id, with_for_update=True, populate_existing=True)
        if job is None:
            return
        hold = ctx.ledger.find_open_reservation(s, FINISHING_REF_TYPE, job_id)
        if hold is not None:
            ctx.ledger.release(s, hold)
        job.credits_charged = Decimal(0)
        _usage(job, llm)
        job.status, job.error, job.finished_at = status, error[:2000], utcnow()
        s.commit()
    except Exception:
        s.rollback()
        log.exception("finishing_fail_bookkeeping_failed")


def sweep_stuck_finishing(ctx: WorkerContext, *, now: datetime | None = None) -> int:
    """Beat task: fail + refund jobs stuck in queued/running past
    ``FINISHING_STUCK_TIMEOUT_MINUTES`` (lost broker message, dead worker)."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=ctx.settings.finishing_stuck_timeout_minutes)
    n = 0
    with ctx.session_factory() as s:
        ids = list(
            s.execute(
                select(FinishingJob.id).where(
                    FinishingJob.status.in_(("queued", "running")),
                    FinishingJob.updated_at < cutoff,
                )
            ).scalars()
        )
        s.rollback()
        for job_id in ids:
            job = s.get(FinishingJob, job_id, with_for_update=True, populate_existing=True)
            if job is None or job.status not in ("queued", "running") or job.updated_at >= cutoff:
                s.rollback()
                continue
            hold = ctx.ledger.find_open_reservation(s, FINISHING_REF_TYPE, job_id)
            if hold is not None:
                ctx.ledger.release(s, hold)
            job.credits_charged = Decimal(0)
            job.status, job.finished_at = "failed", utcnow()
            job.error = "Timeout: the job was lost or timed out before it finished"
            s.commit()
            n += 1
            log.warning("finishing_stuck_failed", job_id=str(job_id))
    return n
