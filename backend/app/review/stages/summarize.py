"""Walkthrough summarizer, cheap role (spec §7 step 11, §7.7)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.platforms.base import FileDiff, PullRequest
from app.review.findings import Candidate
from app.review.llm import LLMLike
from app.review.prompts import SUMMARY_SYSTEM, system_prompt
from app.review.safety import clean_prose, strip_mermaid_links, untrusted
from app.review.schemas import ChangeGroup, PlanTask, WalkthroughSummary
from app.review.stages.triage import TriageOutcome

EFFORT_MINUTES = {1: 5, 2: 10, 3: 20, 4: 45, 5: 90}
TITLE_MAX = 72


def title_requested(title: str, cfg: HootPRConfig) -> bool:
    """``reviews.auto_title_placeholder`` (non-empty) occurs in the PR title, any case."""
    placeholder = cfg.reviews.auto_title_placeholder.strip().lower()
    return bool(placeholder) and placeholder in title.lower()


def _effort(lines: int) -> int:
    return (
        1
        if lines <= 20
        else 2
        if lines <= 100
        else 3
        if lines <= 400
        else 4
        if lines <= 1500
        else 5
    )


def fallback_summary(files: Sequence[FileDiff], tri: TriageOutcome | None) -> WalkthroughSummary:
    effort = _effort(sum(f.additions + f.deletions for f in files))
    # Triage summaries are cheap-model output shaped by the untrusted diff: hardened like any
    # other model text before they reach the walkthrough or the PR description.
    changes = [
        ChangeGroup(
            files=[f.path],
            summary=clean_prose((tri.summaries.get(f.path) if tri else "") or "", 300)
            or f"{f.status} (+{f.additions} -{f.deletions})",
        )
        for f in files
    ]
    return WalkthroughSummary(
        walkthrough=f"This pull request changes {len(files)} file(s).",
        changes=changes,
        sequence_diagrams=[],
        effort=effort,
        effort_minutes=EFFORT_MINUTES[effort],
        pr_summary="\n".join(f"- `{c.files[0]}`: {c.summary}" for c in changes[:20]),
        poem=None,
    )


def _render(
    pr: PullRequest,
    files: Sequence[FileDiff],
    tri: TriageOutcome | None,
    tasks: Sequence[PlanTask],
    kept: Sequence[Candidate],
    cfg: HootPRConfig,
) -> str:
    parts = [untrusted("pr", f"title: {pr.title}\n\n{pr.body[:3000]}")]
    for f in files:
        summary = tri.summaries.get(f.path, "") if tri else ""
        parts.append(
            f"### FILE {f.path}\n"
            + untrusted(f"triage:{f.path}", summary)
            + "\n"
            + untrusted(f"diff:{f.path}", (f.patch or "")[:1500])
        )
    # Task titles and finding titles are model output derived from the diff: data, not orders.
    if tasks:
        parts.append("Review tasks:\n" + untrusted("plan", "; ".join(t.title for t in tasks)))
    if kept:
        parts.append(
            "Findings kept:\n"
            + untrusted("findings", "; ".join(f"{c.severity}: {c.title}" for c in kept[:20]))
        )
    parts.append(f"Poem requested: {'yes' if cfg.reviews.poem else 'no'}")
    parts.append(f"Title requested: {'yes' if title_requested(pr.title, cfg) else 'no'}")
    return "\n\n".join(parts)


def summarize(
    llm: LLMLike,
    files: Sequence[FileDiff],
    tri: TriageOutcome | None,
    tasks: Sequence[PlanTask],
    kept: Sequence[Candidate],
    cfg: HootPRConfig,
    pr: PullRequest,
    *,
    trace: TraceContext,
    host: str | None = None,
) -> tuple[WalkthroughSummary, bool]:
    try:
        res = llm.complete(
            "cheap",
            [
                {"role": "system", "content": system_prompt(SUMMARY_SYSTEM, cfg)},
                {"role": "user", "content": _render(pr, files, tri, tasks, kept, cfg)},
            ],
            response_model=WalkthroughSummary,
            max_output_tokens=3000,
            trace=trace,
        )
    except StructuredOutputError:
        return fallback_summary(files, tri), True
    s = cast(WalkthroughSummary, res.parsed)
    known = [f.path for f in files]
    seen: set[str] = set()
    changes: list[ChangeGroup] = []
    for g in s.changes:
        paths = [p for p in dict.fromkeys(g.files) if p in known and p not in seen]
        if paths:
            seen.update(paths)
            changes.append(ChangeGroup(files=paths, summary=clean_prose(g.summary, 300, host)))
    missing = [p for p in known if p not in seen]
    if missing:
        changes.append(ChangeGroup(files=missing, summary="Other changes."))
    diagrams = [
        strip_mermaid_links(d.strip().replace("```", ""))
        for d in s.sequence_diagrams
        if d.strip().startswith("sequenceDiagram")
    ][:2]

    def clean(text: str, n: int) -> str:
        return clean_prose(text, n, host)

    return WalkthroughSummary(
        walkthrough=clean(s.walkthrough, 4000),
        changes=changes,
        sequence_diagrams=diagrams,
        effort=min(5, max(1, s.effort)),
        effort_minutes=min(600, max(1, s.effort_minutes)),
        pr_summary=clean(s.pr_summary, 3000),
        poem=clean(s.poem, 600) if (cfg.reviews.poem and s.poem) else None,
        title=_title(s.title, host) if title_requested(pr.title, cfg) else None,
    ), False


def _title(title: str | None, host: str | None) -> str | None:
    """One line, hardened, at most ``TITLE_MAX`` characters; ``None`` when empty."""
    if not title:
        return None
    one_line = " ".join(title.split()).strip("`#* ")
    cleaned = clean_prose(one_line, TITLE_MAX, host).strip()
    return cleaned or None
