"""Slop detection (spec §10.2): cheap deterministic signals, then the ``cheap`` model decides.

The model is only asked when at least one signal fires, so ordinary PRs cost nothing extra.
Flagged PRs get a label (``reviews.slop_detection.label``) and a walkthrough note.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.merge.context import render_pr_context
from app.merge.prompts import SLOP_SYSTEM
from app.merge.schemas import SlopVerdict
from app.platforms.base import FileDiff
from app.review.llm import LLMLike
from app.review.prompts import system_prompt
from app.review.safety import clean_prose, untrusted

MIN_CONFIDENCE = 0.7
HUGE_CHANGED_LINES = 3000
HUGE_FILES = 80
CHURN_MIN_FILES = 5
CHURN_RATIO = 0.5
_BOILERPLATE = re.compile(
    r"as an ai\b|as a large language model|i hope this helps|certainly[!,]|here(?:'s| is) the "
    r"(?:updated|improved|refactored)|this pull request (?:introduces|makes) (?:several|various) "
    r"(?:improvements|enhancements)|enhances? (?:the )?overall (?:code )?quality|"
    r"improves? (?:the )?overall (?:readability|maintainability)|generated (?:by|with) "
    r"(?:chatgpt|claude|copilot|an? ai)",
    re.I,
)


@dataclass
class SlopResult:
    signals: list[str] = field(default_factory=list)
    flagged: bool = False
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _whitespace_only(f: FileDiff) -> bool:
    added = [ln.text.strip() for h in f.hunks for ln in h.lines if ln.kind == "add"]
    removed = [ln.text.strip() for h in f.hunks for ln in h.lines if ln.kind == "del"]
    return bool(added or removed) and sorted(x for x in added if x) == sorted(
        x for x in removed if x
    )


def slop_signals(body: str, files: Sequence[FileDiff]) -> list[str]:
    out: list[str] = []
    if _BOILERPLATE.search(body or ""):
        out.append("boilerplate or AI-assistant phrasing in the description")
    changed = sum(f.additions + f.deletions for f in files)
    if changed > HUGE_CHANGED_LINES or len(files) > HUGE_FILES:
        out.append(f"very large diff ({len(files)} files, {changed} changed lines)")
    code = [f for f in files if f.hunks and not f.is_binary]
    churn = [f for f in code if _whitespace_only(f)]
    if len(code) >= CHURN_MIN_FILES and len(churn) / len(code) >= CHURN_RATIO:
        out.append(f"{len(churn)} of {len(code)} files only change formatting")
    return out


def detect_slop(
    llm: LLMLike,
    cfg: HootPRConfig,
    title: str,
    body: str,
    files: Sequence[FileDiff],
    *,
    trace: TraceContext,
    host: str | None,
) -> SlopResult:
    res = SlopResult(signals=slop_signals(body, files))
    if not cfg.reviews.slop_detection.enabled or not res.signals:
        return res
    prompt = (
        "Signals found:\n"
        + untrusted("signals", "\n".join(f"- {s}" for s in res.signals))
        + "\n\n"
        + render_pr_context(title, body, None, files, diff_budget=6000)
    )
    try:
        out = llm.complete(
            "cheap",
            [
                {"role": "system", "content": system_prompt(SLOP_SYSTEM, cfg)},
                {"role": "user", "content": prompt},
            ],
            response_model=SlopVerdict,
            max_output_tokens=400,
            trace=trace,
        )
    except StructuredOutputError:
        return res
    v = cast(SlopVerdict, out.parsed)
    res.confidence = min(1.0, max(0.0, float(v.confidence)))
    res.flagged = bool(v.is_slop) and res.confidence >= MIN_CONFIDENCE
    res.reasons = [clean_prose(" ".join(r.split()), 200, host) for r in v.reasons[:4] if r.strip()]
    return res


def render_slop_note(res: SlopResult) -> str:
    if not res.flagged:
        return ""
    reasons = res.reasons or res.signals
    lines = [
        "> [!WARNING]",
        "> **Possible low-quality (slop) pull request.** HootPR's heuristics flagged this change:",
        *(f"> - {r}" for r in reasons),
        "",
    ]
    return "\n".join(lines)
