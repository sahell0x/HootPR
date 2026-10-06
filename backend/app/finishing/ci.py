"""CI/CD pipeline failure analysis (spec §10.1): GitHub ``workflow_run`` / GitLab ``pipeline``
failures → failed job logs (fetched by the worker) → one upserted analysis comment plus inline
comments on changed lines. Comment-only, so it is metered like a chat reply (hold up to
``CHAT_HOLD_MAX``) and takes a ``chat`` rate-limit slot; one job per (PR, sha, run).
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.billing.ledger import InsufficientCredits
from app.billing.rate_limit import Limited
from app.chat.identity import bot_identity, primary_mention
from app.config.loader import load_effective_config
from app.config.schema import HootPRConfig
from app.events.models import PipelineFailed
from app.finishing.handler import FINISHING_REF_TYPE, FINISHING_TASK
from app.finishing.prompts import CI_ANALYSIS_SYSTEM
from app.finishing.replies import CiItem, ci_marker, render_ci_analysis
from app.knowledge.text import redact_secrets
from app.llm.types import TraceContext
from app.logging import get_logger
from app.models import FinishingJob, PullRequest
from app.platforms.base import GitPlatform, InlineComment, RepoRef
from app.platforms.base import PullRequest as LivePR
from app.platforms.factory import NotInstalled, close_platform, repo_ref
from app.review.llm import MeteredLLM
from app.review.pipeline import find_reviewable_repo
from app.review.prompts import system_prompt
from app.review.safety import clean_prose, repo_host, untrusted
from app.settings import Settings
from app.worker.context import WorkerContext

log = get_logger(__name__)
DIFF_MAX_CHARS = 20_000
MAX_INLINE = 5


class CiFailure(BaseModel):
    job: str = Field(description="Failed job name, exactly as given.")
    title: str = Field(description="One-line title of the failure.")
    root_cause: str = Field(description="2-4 sentences.")
    fix: str = Field(description="Concrete fix.")
    path: str | None = Field(description="Changed file the failure points at, or null.")
    line: int | None = Field(description="New-side line in that file, or null.")
    caused_by_pr: bool = Field(description="False for flaky/infrastructure failures.")


class CiAnalysis(BaseModel):
    failures: list[CiFailure]


def handle_pipeline_failed(ctx: WorkerContext, ev: PipelineFailed) -> str:
    """``events.process`` handler: queue a ``ci_analysis`` job (or ignore)."""
    with ctx.session_factory() as s:
        found = find_reviewable_repo(s, ev.provider, ev.repo.provider_repo_id)
        if found is None:
            return "ignored"
        repo, org, _ = found
        q = select(PullRequest).where(PullRequest.repo_id == repo.id)
        if ev.pr_number is not None:
            q = q.where(PullRequest.number == ev.pr_number)
        else:
            q = q.where(PullRequest.head_sha == ev.sha, PullRequest.state == "open")
        pr = s.execute(q.limit(1)).scalar_one_or_none()
        if pr is None or pr.state != "open":
            return "ignored"
        if pr.head_sha and ev.sha and pr.head_sha != ev.sha:
            return "ignored"  # a run for an older commit
        try:
            platform = ctx.platforms(s, repo)
        except NotInstalled:
            return "ignored"
        try:
            cfg = load_effective_config(
                platform, repo_ref(repo), pr.base_ref or repo.default_branch,
                repo.settings, org.settings,
            ).config  # fmt: skip
        finally:
            close_platform(platform)
        if not cfg.reviews.finishing_touches.ci_analysis.enabled:
            return "ignored"
        run_id = ev.run_id or ""
        dupe = s.execute(
            select(FinishingJob.id).where(
                FinishingJob.pr_id == pr.id,
                FinishingJob.kind == "ci_analysis",
                FinishingJob.head_sha == ev.sha,
                FinishingJob.meta["run_id"].astext == run_id,
            )
        ).first()
        if dupe is not None:
            return "ignored"
        job = FinishingJob(
            org_id=org.id,
            pr_id=pr.id,
            kind="ci_analysis",
            trigger="webhook",
            delivery="comment",
            status="queued",
            requested_by="",
            head_sha=ev.sha,
            meta={"run_id": run_id, "run_url": ev.url},
        )
        s.add(job)
        s.flush()
        limited = ctx.limiter.check_and_consume(org.id, "chat")
        if isinstance(limited, Limited):
            job.status = "rate_limited"
            s.commit()
            return "processed"
        st = ctx.settings
        hold = ctx.ledger.reserve_up_to(
            s, org.id, st.chat_hold_max, st.chat_min_charge, FINISHING_REF_TYPE, job.id
        )
        if isinstance(hold, InsufficientCredits):
            job.status = "no_credits"
            s.commit()
            return "processed"
        s.commit()
        try:
            ctx.queue.enqueue(FINISHING_TASK, str(job.id))
        except Exception as exc:
            log.exception("ci_analysis_enqueue_failed")
            held = ctx.ledger.find_open_reservation(s, FINISHING_REF_TYPE, job.id)
            if held is not None:
                ctx.ledger.release(s, held)
            job.status, job.error = "failed", f"EnqueueFailed: {type(exc).__name__}"
            s.commit()
        return "processed"


def _hard(text: str, settings: Settings, provider: str, n: int) -> str:
    return clean_prose(redact_secrets(text), n, repo_host(provider, settings))


def run_ci_analysis(
    ctx: WorkerContext,
    platform: GitPlatform,
    ref: RepoRef,
    live: LivePR,
    cfg: HootPRConfig,
    llm: MeteredLLM,
    trace: TraceContext,
    bot_username: str | None = None,
) -> None:
    """Called by ``finishing.run`` for ``ci_analysis`` jobs (raises NothingToDo-like errors
    through the runner)."""
    from app.finishing.run import NothingToDo

    settings = ctx.settings
    logs = platform.get_ci_logs(
        ref, live.head_sha, max_jobs=settings.ci_log_max_jobs, max_log_kb=settings.ci_log_max_kb
    )
    if not logs:
        raise NothingToDo("no failed CI jobs were found.")
    diffs = platform.get_diff(ref, live.number)
    changed = {d.path: d.changed_new_lines() for d in diffs}
    diff_text = ""
    for d in diffs:
        if d.patch and len(diff_text) < DIFF_MAX_CHARS:
            diff_text += f"### {d.path}\n{d.patch[: DIFF_MAX_CHARS - len(diff_text)]}\n"
    user = "\n\n".join(
        [
            "Failed jobs:",
            *[
                f"## Job: {j.name} (step: {j.failed_step or '-'})\n"
                + untrusted(f"ci-log:{j.name}", j.log_tail)
                for j in logs
            ],
            "Pull request diff:\n" + untrusted("diff", diff_text or "(empty)"),
        ]
    )
    res = llm.complete(
        "review",
        [
            {"role": "system", "content": system_prompt(CI_ANALYSIS_SYSTEM, cfg)},
            {"role": "user", "content": user},
        ],
        response_model=CiAnalysis,
        max_output_tokens=3000,
        trace=trace,
    )
    parsed = res.parsed if isinstance(res.parsed, CiAnalysis) else CiAnalysis(failures=[])
    provider = ref.provider
    items: list[CiItem] = []
    inline: list[InlineComment] = []
    for f in parsed.failures[:10]:
        valid_anchor = bool(f.path and f.line and f.line in changed.get(f.path, set()))
        item = CiItem(
            job=_hard(f.job, settings, provider, 200),
            title=_hard(f.title, settings, provider, 200),
            root_cause=_hard(f.root_cause, settings, provider, 1500),
            fix=_hard(f.fix, settings, provider, 1500),
            path=f.path if valid_anchor else None,
            line=f.line if valid_anchor else None,
            caused_by_pr=f.caused_by_pr,
        )
        items.append(item)
        if valid_anchor and f.caused_by_pr and f.path and f.line and len(inline) < MAX_INLINE:
            inline.append(
                InlineComment(
                    path=f.path,
                    end_line=f.line,
                    body=f"🚨 **CI failure — {item.title}**\n\n{item.root_cause}\n\n"
                    f"**Fix:** {item.fix}",
                )
            )
    job_urls = {j.name: j.url for j in logs if j.url}
    identity = bot_identity(settings, provider, bot_username)
    body = render_ci_analysis(live.head_sha, items, job_urls, primary_mention(identity))
    platform.upsert_comment(ref, live.number, ci_marker(live.head_sha), body)
    if inline:
        try:
            platform.post_review(ref, live.number, live.head_sha, None, inline)
        except Exception:
            log.warning("ci_inline_comments_failed", exc_info=True)
