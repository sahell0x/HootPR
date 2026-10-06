"""Unified diff hunk parser used for both providers (GitHub ``patch``, GitLab ``diff``)."""

from __future__ import annotations

import re

from app.platforms.base import DiffLine, FileDiff, FileStatus, Hunk

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def parse_patch(patch: str) -> tuple[Hunk, ...]:
    """Parse the hunks of a unified diff; anything before the first ``@@`` is ignored."""
    hunks: list[Hunk] = []
    header: tuple[int, int, int, int, str] | None = None
    lines: list[DiffLine] = []
    old_no = new_no = 0

    def flush() -> None:
        if header is not None:
            os_, oc, ns, nc, h = header
            hunks.append(Hunk(os_, oc, ns, nc, h, tuple(lines)))

    for raw in patch.splitlines():
        m = _HUNK.match(raw)
        if m:
            flush()
            lines = []
            old_no, new_no = int(m[1]), int(m[3])
            header = (
                old_no,
                int(m[2]) if m[2] is not None else 1,
                new_no,
                int(m[4]) if m[4] is not None else 1,
                m[5].strip(),
            )
            continue
        if header is None or raw.startswith("\\"):
            continue
        tag, text = raw[:1], raw[1:]
        if tag == "+":
            lines.append(DiffLine("add", text, None, new_no))
            new_no += 1
        elif tag == "-":
            lines.append(DiffLine("del", text, old_no, None))
            old_no += 1
        else:
            lines.append(DiffLine("context", text, old_no, new_no))
            old_no += 1
            new_no += 1
    flush()
    return tuple(hunks)


def count_changes(hunks: tuple[Hunk, ...]) -> tuple[int, int]:
    adds = sum(1 for h in hunks for ln in h.lines if ln.kind == "add")
    dels = sum(1 for h in hunks for ln in h.lines if ln.kind == "del")
    return adds, dels


def build_file_diff(
    path: str, patch: str | None, status: FileStatus, old_path: str | None = None
) -> FileDiff:
    """A missing/empty patch means the provider did not render a text diff (binary/too large)."""
    if not patch:
        return FileDiff(path, old_path, status, 0, 0, None, (), is_binary=True)
    hunks = parse_patch(patch)
    adds, dels = count_changes(hunks)
    return FileDiff(path, old_path, status, adds, dels, patch, hunks)
