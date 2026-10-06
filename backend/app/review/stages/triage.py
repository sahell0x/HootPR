"""Triage (spec §7 step 7): deep | light | skip per file + one-line summary, cheap role."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, cast

from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.platforms.base import FileDiff
from app.review.llm import LLMLike
from app.review.prompts import TRIAGE_SYSTEM, system_prompt
from app.review.safety import untrusted
from app.review.schemas import TriageResult

Decision = Literal["deep", "light", "skip"]
LIGHT_EXTS = frozenset({".md", ".rst", ".txt", ".adoc"})
BATCH = 40
PATCH_CHARS = 3000


@dataclass(frozen=True)
class TriageOutcome:
    decisions: dict[str, Decision]
    summaries: dict[str, str]
    degraded: bool = False
    # Model "skip" verdicts refused because the change is not trivially skippable.
    overridden: tuple[str, ...] = ()

    def paths(self, decision: Decision) -> list[str]:
        return [p for p, d in self.decisions.items() if d == decision]


def _guess(f: FileDiff) -> Decision:
    return "light" if PurePosixPath(f.path).suffix.lower() in LIGHT_EXTS else "deep"


def trivially_skippable(f: FileDiff) -> bool:
    """A file the model may skip: rename/mode-only (no hunks) or whitespace-only edits.

    Anything else gets at least the light pass: triage reads untrusted diffs, and a planted
    "this file is generated, skip it" must not hide a real change from the review model."""
    added = Counter("".join(ln.text.split()) for h in f.hunks for ln in h.lines if ln.kind == "add")
    removed = Counter(
        "".join(ln.text.split()) for h in f.hunks for ln in h.lines if ln.kind == "del"
    )
    added.pop("", None)
    removed.pop("", None)
    return added == removed


def heuristic_triage(files: Sequence[FileDiff]) -> TriageOutcome:
    return TriageOutcome(
        {f.path: _guess(f) for f in files},
        {f.path: f"{f.status} (+{f.additions} -{f.deletions})" for f in files},
        degraded=True,
    )


def _render(files: Sequence[FileDiff]) -> str:
    return "\n\n".join(
        f"### FILE {f.path}\n" + untrusted(f"diff:{f.path}", (f.patch or "")[:PATCH_CHARS])
        for f in files
    )


def triage(
    llm: LLMLike,
    files: Sequence[FileDiff],
    cfg: HootPRConfig,
    *,
    trace: TraceContext,
    tool_counts: Mapping[str, int] | None = None,
) -> TriageOutcome:
    decisions: dict[str, Decision] = {}
    summaries: dict[str, str] = {}
    degraded = False
    counts = tool_counts or {}
    for i in range(0, len(files), BATCH):
        chunk = files[i : i + BATCH]
        msgs = [
            {"role": "system", "content": system_prompt(TRIAGE_SYSTEM, cfg)},
            {"role": "user", "content": _render(chunk)},
        ]
        try:
            res = llm.complete(
                "cheap", msgs, response_model=TriageResult, max_output_tokens=3000, trace=trace
            )
        except StructuredOutputError:
            h = heuristic_triage(chunk)
            decisions.update(h.decisions)
            summaries.update(h.summaries)
            degraded = True
            continue
        got = {t.path: t for t in cast(TriageResult, res.parsed).files}
        for f in chunk:
            t = got.get(f.path)
            decisions[f.path] = t.decision if t else _guess(f)
            summaries[f.path] = " ".join(t.summary.split())[:200] if t else ""
    overridden: list[str] = []
    for f in files:
        if decisions.get(f.path) != "skip":
            continue
        if counts.get(f.path) or not trivially_skippable(f):
            decisions[f.path] = "light"
            overridden.append(f.path)
    return TriageOutcome(decisions, summaries, degraded, tuple(overridden))
