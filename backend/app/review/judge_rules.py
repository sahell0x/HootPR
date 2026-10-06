"""Deterministic judge (spec §7.6.1): anchors, suggestions, fingerprints, merging."""

from __future__ import annotations

from collections.abc import Sequence

from app.review.anchoring import DiffIndex, fingerprint
from app.review.findings import Candidate, rank_key

SECURITY_SLACK = 10
MAX_SUGGESTION_CHARS = 5000
MAX_EVIDENCE = 10


def suggestion_applies(diff: DiffIndex, path: str, start: int, end: int, suggestion: str) -> bool:
    """A suggestion applies when it replaces lines of one hunk and actually changes them."""
    if len(suggestion) > MAX_SUGGESTION_CHARS:
        return False
    texts = [diff.line_text(path, n) for n in range(start, end + 1)]
    if any(t is None for t in texts):
        return False
    if len({diff.hunk_of(path, n) for n in range(start, end + 1)}) != 1:
        return False
    current = "\n".join(t for t in texts if t is not None)
    return current.rstrip() != suggestion.rstrip()


def _anchor(c: Candidate, diff: DiffIndex) -> str | None:
    if not diff.has_path(c.path):
        return "path_not_in_diff"
    start, end = sorted((c.start, c.end_line))
    hs, he = diff.hunk_of(c.path, start), diff.hunk_of(c.path, end)
    if he is None or hs != he:
        if c.category == "security":
            near = diff.nearest_added(c.path, end, within=SECURITY_SLACK)
            if near is not None:
                c.anchor_note = f"re-anchored from line {c.end_line}"
                c.start_line, c.end_line, c.suggestion = None, near, None
                return None
        return "outside_changed_hunk"
    c.start_line, c.end_line = (start if start != end else None), end
    return None


def _overlap(a: Candidate, b: Candidate) -> bool:
    return a.start <= b.end_line and b.start <= a.end_line


def deterministic_judge(
    cands: Sequence[Candidate], diff: DiffIndex, prior: frozenset[str]
) -> list[Candidate]:
    """Return the surviving candidates ranked; dropped/merged ones are marked in place."""
    alive: list[Candidate] = []
    for c in cands:
        reason = _anchor(c, diff)
        if (
            reason is None
            and c.suggestion is not None
            and not suggestion_applies(diff, c.path, c.start, c.end_line, c.suggestion)
        ):
            reason = "suggestion_does_not_apply"
        if reason:
            c.drop(reason)
            continue
        c.fingerprint = fingerprint(
            c.path, diff.line_text(c.path, c.end_line) or str(c.end_line), c.category
        )
        if c.fingerprint in prior:
            c.drop("already_posted")
            continue
        alive.append(c)
    merged: list[Candidate] = []
    for c in sorted(alive, key=rank_key):
        twin = next(
            (
                k
                for k in merged
                if k.path == c.path
                and k.category == c.category
                and (k.fingerprint == c.fingerprint or _overlap(k, c))
            ),
            None,
        )
        if twin is None:
            merged.append(c)
            continue
        c.verdict, c.reason = "merge", f"merged into: {twin.title}"
        twin.evidence = list(dict.fromkeys([*twin.evidence, *c.evidence]))[:MAX_EVIDENCE]
    return merged
