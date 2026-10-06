"""LLM verification + thresholds (spec §7.6 steps 2-3, plan Q5)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.review.anchoring import DiffIndex
from app.review.context import path_instructions_for
from app.review.findings import Candidate, rank_key
from app.review.llm import LLMLike
from app.review.prompts import JUDGE_SYSTEM, PROFILE_NOTES, system_prompt
from app.review.safety import untrusted
from app.review.schemas import JudgeBatch
from app.settings import Settings


def _render(batch: Sequence[Candidate], diff: DiffIndex, cfg: HootPRConfig) -> str:
    blocks: list[str] = []
    for i, c in enumerate(batch):
        text = f"title: {c.title}\n\n{c.body}"
        if c.suggestion:
            text += f"\n\nsuggestion:\n{c.suggestion}"
        if c.evidence:
            text += "\n\nevidence:\n" + "\n".join(c.evidence)
        blocks.append(
            "\n".join(
                [
                    f"### FINDING {i}",
                    f"path: {c.path}",
                    f"lines: {c.start}-{c.end_line}",
                    f"severity: {c.severity}",
                    f"category: {c.category}",
                    f"confidence: {c.confidence:.2f}",
                    untrusted(f"finding:{i}", text),
                    untrusted(f"code:{c.path}", diff.excerpt(c.path, c.start, c.end_line)),
                ]
            )
        )
        if rules := path_instructions_for(c.path, cfg):
            blocks[-1] += "\n" + untrusted(f"repo_instructions:{c.path}", "\n".join(rules))
    return "\n\n".join(blocks)


def llm_verify(
    llm: LLMLike,
    cands: Sequence[Candidate],
    diff: DiffIndex,
    cfg: HootPRConfig,
    *,
    batch_size: int,
    trace: TraceContext,
    learnings: str = "",
) -> bool:
    """Verify ``cands`` in batches; ``learnings`` (a ``<team_learnings>`` block) is appended to
    every batch so findings the team said it does not want are dropped (spec §8)."""
    degraded = False
    system = system_prompt(f"{JUDGE_SYSTEM}\n\n{PROFILE_NOTES[cfg.reviews.profile]}", cfg)
    size = max(1, min(10, batch_size))
    for start in range(0, len(cands), size):
        batch = list(cands[start : start + size])
        user = _render(batch, diff, cfg) + (f"\n\n{learnings}" if learnings else "")
        try:
            res = llm.complete(
                "review",
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_model=JudgeBatch,
                max_output_tokens=2000,
                trace=trace,
            )
        except StructuredOutputError:
            for c in batch:
                c.drop("judge_unavailable")
            degraded = True
            continue
        verdicts = {v.index: v for v in cast(JudgeBatch, res.parsed).verdicts}
        dup_of = {i: v.duplicate_of for i, v in verdicts.items() if v.duplicate_of is not None}
        for j, c in enumerate(batch):
            v = verdicts.get(j)
            if v is None:
                c.drop("judge_no_verdict")
                continue
            reason = " ".join(v.reason.split())[:300] or v.verdict
            if v.verdict == "drop":
                c.drop(reason)
                continue
            c.verdict, c.reason = "keep", reason
            if v.adjusted_severity:
                c.severity = v.adjusted_severity
        _fold_duplicates(batch, dup_of)
    return degraded


def _fold_duplicates(batch: list[Candidate], dup_of: dict[int, int]) -> None:
    """One comment per problem (CodeRabbit's "Also applies to"): a kept finding the judge marked
    as a duplicate of another kept finding in the same file merges into it."""
    for j, target in dup_of.items():
        seen = {j}
        while target in dup_of and target not in seen:  # follow chains to the root
            seen.add(target)
            target = dup_of[target]
        if target in seen or not (0 <= j < len(batch) and 0 <= target < len(batch)):
            continue
        c, primary = batch[j], batch[target]
        if not (c.alive and primary.alive and c.path == primary.path):
            continue
        c.verdict, c.reason = "merge", f"merged into: {primary.title}"
        primary.evidence = list(dict.fromkeys([*primary.evidence, *c.evidence]))[:10]
        rng = (c.start, c.end_line)
        overlaps = c.start <= primary.end_line and primary.start <= c.end_line
        if not overlaps and rng not in primary.also_applies:
            primary.also_applies.append(rng)
        primary.also_applies.sort()


def min_confidence(cfg: HootPRConfig, settings: Settings) -> float:
    if cfg.reviews.profile == "assertive":
        return settings.judge_min_confidence_assertive
    return settings.judge_min_confidence_chill


def apply_thresholds(
    cands: Sequence[Candidate],
    *,
    profile: str,
    min_conf: float,
    max_comments: int,
    use_confidence: bool = True,
) -> tuple[list[Candidate], list[Candidate]]:
    kept: list[Candidate] = []
    for c in cands:
        if not c.alive:
            continue
        if use_confidence and c.confidence < min_conf:
            c.drop(f"low_confidence ({c.confidence:.2f} < {min_conf:.2f})")
            continue
        if c.verdict is None:
            c.verdict, c.reason = "keep", c.reason or "kept without LLM verification"
        kept.append(c)
    inline: list[Candidate] = []
    additional: list[Candidate] = []
    for c in sorted(kept, key=rank_key):
        if (profile == "chill" and c.severity == "nitpick") or len(inline) >= max_comments:
            c.placement = "additional"
            additional.append(c)
        else:
            c.placement = "inline"
            inline.append(c)
    return inline, additional
