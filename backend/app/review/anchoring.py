"""New-side line index over the PR diff: anchoring, excerpts, fingerprints (spec §7.1, §7.6)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from app.platforms.base import FileDiff


class DiffIndex:
    """Every new-side line visible in the diff (context + added), with its hunk index."""

    def __init__(self, files: Sequence[FileDiff]) -> None:
        self._lines: dict[str, dict[int, tuple[str, int]]] = {}
        self._added: dict[str, list[int]] = {}
        self._old: dict[str, dict[int, int]] = {}
        self._old_path: dict[str, str] = {}
        for f in files:
            lines: dict[int, tuple[str, int]] = {}
            added: list[int] = []
            old: dict[int, int] = {}
            for hi, h in enumerate(f.hunks):
                for ln in h.lines:
                    if ln.new_line is None:
                        continue
                    lines[ln.new_line] = (ln.text, hi)
                    if ln.kind == "add":
                        added.append(ln.new_line)
                    elif ln.old_line is not None:
                        old[ln.new_line] = ln.old_line
            self._lines[f.path] = lines
            self._old[f.path] = old
            self._old_path[f.path] = f.old_path or f.path
            self._added[f.path] = sorted(added)

    def has_path(self, path: str) -> bool:
        return path in self._lines

    def hunk_of(self, path: str, line: int) -> int | None:
        hit = self._lines.get(path, {}).get(line)
        return hit[1] if hit else None

    def old_line(self, path: str, line: int) -> int | None:
        """Old-side line of an unchanged (context) new-side line; None for added lines."""
        return self._old.get(path, {}).get(line)

    def old_path(self, path: str) -> str | None:
        """The file's path before the change (differs from ``path`` for renames)."""
        return self._old_path.get(path)

    def line_text(self, path: str, line: int) -> str | None:
        hit = self._lines.get(path, {}).get(line)
        return hit[0] if hit else None

    def added_lines(self, path: str) -> list[int]:
        return list(self._added.get(path, []))

    def nearest_added(self, path: str, line: int, within: int) -> int | None:
        best = min(self._added.get(path, []), key=lambda n: (abs(n - line), n), default=None)
        return best if best is not None and abs(best - line) <= within else None

    def excerpt(self, path: str, start: int, end: int, context: int = 5) -> str:
        lines = self._lines.get(path, {})
        return "\n".join(
            f"{n:>4}  {lines[n][0]}"
            for n in range(max(1, start - context), end + context + 1)
            if n in lines
        )


def fingerprint(path: str, line_text: str, category: str) -> str:
    """Stable id of a finding across pushes: path + whitespace-normalized code line + category."""
    normalized = " ".join(line_text.split())
    return hashlib.sha256(f"{path}\n{normalized}\n{category}".encode()).hexdigest()[:32]
