"""``@hootpr summary``: regenerate the "Summary by HootPR" block (phase-3 R23)."""

from __future__ import annotations

from app.config.schema import HootPRConfig
from app.formatting.walkthrough import SUMMARY_MARKER, render_summary_block
from app.llm.types import TraceContext
from app.platforms.base import GitPlatform, PullRequest, RepoRef
from app.review.llm import LLMLike
from app.review.safety import repo_host
from app.review.stages.diff_filter import apply_budget, filter_files
from app.review.stages.summarize import summarize
from app.settings import Settings


def regenerate_summary(
    platform: GitPlatform,
    ref: RepoRef,
    pr: PullRequest,
    cfg: HootPRConfig,
    llm: LLMLike,
    settings: Settings,
    trace: TraceContext,
) -> bool:
    """Summarize the whole PR diff into the description block; ``False`` when
    ``high_level_summary`` is off or nothing is reviewable."""
    if not cfg.reviews.high_level_summary:
        return False
    fr = filter_files(platform.get_diff(ref, pr.number), cfg)
    kept = apply_budget(
        fr.kept, max_files=settings.review_max_files, max_lines=settings.review_max_changed_lines
    ).kept
    if not kept:
        return False
    summary, _ = summarize(
        llm, kept, None, [], [], cfg, pr, trace=trace, host=repo_host(ref.provider, settings)
    )
    if not summary.pr_summary.strip():
        return False
    platform.update_pr_description(
        ref,
        pr.number,
        SUMMARY_MARKER,
        render_summary_block(summary.pr_summary),
        placeholder=cfg.reviews.high_level_summary_placeholder or None,
    )
    return True
