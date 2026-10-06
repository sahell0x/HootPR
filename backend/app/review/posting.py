"""Posting (spec §7.7, §7.9): one review with inline comments, the walkthrough comment (edited in
place) and the "Summary by HootPR" block in the PR description.

When GitHub rejects the batched review with 422 (a line moved under us), every comment is
re-anchored to the nearest changed line and the review is retried once; whatever still cannot be
posted moves into the walkthrough's "Comments that could not be posted inline" section.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.billing.pricing import ordered_stages
from app.config.schema import HootPRConfig
from app.formatting.review_comment import render_inline, render_review_body
from app.formatting.walkthrough import (
    SUMMARY_MARKER,
    WALKTHROUGH_MARKER,
    ChangeRow,
    NoteComment,
    ReviewDetails,
    WalkthroughData,
    render_summary_block,
    render_walkthrough,
)
from app.logging import get_logger
from app.platforms.base import GitPlatform, InlineComment, PlatformError, RepoRef, ReviewEvent
from app.review.anchoring import DiffIndex
from app.review.engine import EngineInputs, EngineResult
from app.review.findings import Candidate
from app.review.safety import harden_text
from app.review.stages.summarize import title_requested
from app.security.blast_radius import render_section

log = get_logger(__name__)
BLOCKING = ("critical", "major")
REANCHOR_WITHIN = 5
LEARNING_DETAIL_CHARS = 100


@dataclass
class PostOutcome:
    walkthrough_id: str
    posted: int
    unposted: list[Candidate] = field(default_factory=list)


def make_details(
    result: EngineResult,
    inputs: EngineInputs,
    credits: Decimal,
    reserved: Decimal | None = None,
) -> ReviewDetails:
    """``credits``: what the review will be charged; ``reserved``: its hold (None: flat line)."""
    return ReviewDetails(
        head_sha=inputs.head_sha,
        base_sha=result.base_sha or inputs.base_sha,
        incremental=result.incremental,
        config_source=inputs.config_source,
        tools=tuple(result.tool_runs),
        skipped_files=tuple(result.skipped),
        models=tuple(result.models),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=result.cost_usd,
        credits_charged=credits,
        files_reviewed=len(result.reviewed_files),
        degraded=dict(result.degraded),
        learnings_used=tuple(
            harden_text(" ".join(h.text.split()), LEARNING_DETAIL_CHARS)
            for h in result.learnings_used
        ),
        guidelines=tuple(result.guidelines_used),
        credits_reserved=reserved,
        credits_by_stage=tuple(ordered_stages(result.credits_by_stage)),
        budget_reached=result.degraded.get("credit_budget") == "reached",
    )


def reanchor(c: Candidate, diff: DiffIndex) -> bool:
    """Move ``c`` to the nearest added line (single-line); False when none is close enough.

    A moved comment loses its suggestion: the replacement was written for other lines.
    """
    near = diff.nearest_added(c.path, c.end_line, within=REANCHOR_WITHIN)
    if near is None:
        return False
    if near != c.end_line or c.start_line is not None:
        c.anchor_note = c.anchor_note or f"re-anchored from line {c.end_line}"
        c.suggestion = None
    c.start_line, c.end_line = None, near
    return True


def _comment(c: Candidate, diff: DiffIndex) -> InlineComment:
    start = c.start_line if c.start_line and c.start_line < c.end_line else None
    return InlineComment(
        c.path,
        c.end_line,
        render_inline(c),
        start_line=start,
        suggestion=c.suggestion,
        old_line=diff.old_line(c.path, c.end_line),
        old_path=diff.old_path(c.path),
    )


def _try_post(
    platform: GitPlatform,
    ref: RepoRef,
    number: int,
    head_sha: str,
    body: str,
    cands: list[Candidate],
    event: ReviewEvent,
    diff: DiffIndex,
) -> list[str] | None:
    """Comment ids (``""`` = that comment failed), or None when the whole review got a 422."""
    try:
        return platform.post_review(
            ref, number, head_sha, body, [_comment(c, diff) for c in cands], event=event
        )
    except PlatformError as exc:
        if exc.status_code != 422:
            raise
        log.warning("post_review_rejected", status=exc.status_code, comments=len(cands))
        return None


def post_results(
    platform: GitPlatform,
    ref: RepoRef,
    number: int,
    head_sha: str,
    result: EngineResult,
    cfg: HootPRConfig,
    details: ReviewDetails,
    warnings: Sequence[str],
    *,
    diff: DiffIndex,
    pr_title: str | None = None,
    extra_sections: Sequence[str] = (),
) -> PostOutcome:
    inline = list(result.inline)
    unposted: list[Candidate] = []
    event: ReviewEvent = "COMMENT"
    if cfg.reviews.request_changes_workflow and any(c.severity in BLOCKING for c in inline):
        event = "REQUEST_CHANGES"
    if inline:
        body = render_review_body(len(inline), len(result.additional))
        attempt = inline
        ids = _try_post(platform, ref, number, head_sha, body, attempt, event, diff)
        if ids is None:
            attempt = [c for c in inline if reanchor(c, diff)]
            unposted += [c for c in inline if c not in attempt]
            ids = None
            if attempt:
                body = render_review_body(len(attempt), len(result.additional))
                ids = _try_post(platform, ref, number, head_sha, body, attempt, event, diff)
            if ids is None:
                unposted += attempt
                ids, attempt = [], []
        for i, c in enumerate(attempt):
            cid = ids[i] if i < len(ids) else ""
            if cid:
                c.posted, c.provider_comment_id = True, cid
            else:
                unposted.append(c)
    for c in unposted:
        c.placement, c.posted = "unposted", False
    posted = sum(c.posted for c in inline)
    s = result.summary
    data = WalkthroughData(
        walkthrough=s.walkthrough,
        changes=tuple(ChangeRow(tuple(g.files), g.summary) for g in s.changes),
        sequence_diagrams=tuple(s.sequence_diagrams),
        effort=s.effort,
        effort_minutes=s.effort_minutes,
        poem=s.poem,
        actionable=posted,
        additional=tuple(NoteComment.from_candidate(c) for c in result.additional),
        unposted=tuple(NoteComment.from_candidate(c) for c in unposted),
        warnings=tuple(warnings),
        details=details,
        extra_sections=(render_section(result.blast_radius), *extra_sections),
    )
    wid = platform.upsert_comment(
        ref, number, WALKTHROUGH_MARKER, render_walkthrough(data, cfg.reviews)
    )
    if cfg.reviews.high_level_summary and s.pr_summary.strip():
        try:
            platform.update_pr_description(
                ref,
                number,
                SUMMARY_MARKER,
                render_summary_block(s.pr_summary),
                placeholder=cfg.reviews.high_level_summary_placeholder or None,
            )
        except Exception:
            # The walkthrough already carries the summary; a locked description is not fatal.
            log.exception("pr_description_update_failed")
    if pr_title is not None and s.title and title_requested(pr_title, cfg):
        try:
            platform.update_pr_title(ref, number, s.title)
        except Exception:
            log.exception("pr_title_update_failed")
    return PostOutcome(wid, posted, unposted)
