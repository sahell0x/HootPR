"""Change Stack workspace assembly (spec §10.5): snapshots, task-grouped files, findings.

Pure functions over ORM rows / diff objects so they are unit-testable without a database.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from app.analytics import schemas as A
from app.models import Finding, Review, ReviewTask
from app.platforms.base import FileDiff

OTHER_GROUP = "Other changes"
OTHER_RATIONALE = "Files the review plan did not assign to a task (or reviewed incrementally)."
SNAPSHOT_STATUSES = frozenset({"completed"})

_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".json": "json",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "ini",
    ".ini": "ini",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".xml": "xml",
    ".vue": "html",
    ".tf": "hcl",
}
_NAMES = {"dockerfile": "dockerfile", "makefile": "makefile"}


def language_for(path: str) -> str:
    """Monaco language id for ``path`` (``plaintext`` when unknown)."""
    p = PurePosixPath(path)
    return _NAMES.get(p.name.lower()) or _LANG.get(p.suffix.lower(), "plaintext")


def snapshots(reviews: Sequence[Review], head_sha: str) -> list[A.CsSnapshot]:
    """One snapshot per reviewed head SHA (the newest completed review wins), newest first."""
    seen: dict[str, A.CsSnapshot] = {}
    for r in sorted(reviews, key=lambda r: r.created_at, reverse=True):
        if r.status not in SNAPSHOT_STATUSES or r.head_sha in seen:
            continue
        seen[r.head_sha] = A.CsSnapshot(
            review_id=str(r.id),
            head_sha=r.head_sha,
            base_sha=r.base_sha,
            status=r.status,
            trigger=r.trigger,
            findings=r.findings_posted,
            created_at=r.created_at,
            stale=r.head_sha != head_sha,
        )
    return list(seen.values())


def pick_snapshot(snaps: Sequence[A.CsSnapshot], sha: str | None) -> A.CsSnapshot | None:
    if sha:
        for s in snaps:
            if s.head_sha == sha or s.head_sha.startswith(sha):
                return s
        return None
    return snaps[0] if snaps else None


def relevant_findings(
    findings: Iterable[tuple[Finding, Review]], snapshot_created: datetime | None
) -> list[Finding]:
    """Findings visible at a snapshot: kept (not dropped by the judge), from reviews up to the
    snapshot, de-duplicated by fingerprint (the newest wins)."""
    best: dict[str, tuple[Finding, Review]] = {}
    for f, r in findings:
        if f.judge_verdict == "drop" and not f.posted:
            continue
        if snapshot_created is not None and r.created_at > snapshot_created:
            continue
        cur = best.get(f.fingerprint)
        if cur is None or r.created_at > cur[1].created_at:
            best[f.fingerprint] = (f, r)
    out = [f for f, _ in best.values()]
    rank = {"critical": 0, "major": 1, "minor": 2, "nitpick": 3}
    out.sort(key=lambda f: (f.path, f.end_line, rank.get(f.severity, 9)))
    return out


def finding_out(f: Finding) -> A.CsFinding:
    return A.CsFinding(
        id=str(f.id),
        path=f.path,
        start_line=f.start_line,
        end_line=f.end_line,
        side=f.side,
        severity=f.severity,
        category=f.category,
        title=f.title,
        body=f.body,
        suggestion=f.suggestion,
        status=f.status,
        posted=f.posted,
    )


@dataclass(frozen=True)
class TaskLike:
    ordinal: int
    title: str
    rationale: str
    files: tuple[str, ...]


def task_like(t: ReviewTask) -> TaskLike:
    return TaskLike(t.ordinal, t.title, t.rationale, tuple(t.files or ()))


def group_files(
    diff: Sequence[FileDiff], tasks: Sequence[TaskLike], findings: Sequence[Finding]
) -> list[A.CsGroup]:
    """The diff's files grouped by planner task (task order; a file lands in its first task),
    then everything else under ``OTHER_GROUP``."""
    per_path: dict[str, int] = {}
    for f in findings:
        per_path[f.path] = per_path.get(f.path, 0) + 1
    by_path = {d.path: d for d in diff}
    placed: set[str] = set()
    groups: list[A.CsGroup] = []

    def cs_file(d: FileDiff) -> A.CsFile:
        return A.CsFile(
            path=d.path,
            old_path=d.old_path,
            status=d.status,
            additions=d.additions,
            deletions=d.deletions,
            findings=per_path.get(d.path, 0),
        )

    for t in sorted(tasks, key=lambda t: t.ordinal):
        files = [by_path[p] for p in t.files if p in by_path and p not in placed]
        if not files:
            continue
        placed.update(d.path for d in files)
        groups.append(
            A.CsGroup(title=t.title, rationale=t.rationale, files=[cs_file(d) for d in files])
        )
    rest = [d for d in diff if d.path not in placed]
    if rest:
        groups.append(
            A.CsGroup(
                title=OTHER_GROUP if groups else "Changed files",
                rationale=OTHER_RATIONALE if groups else "",
                files=[cs_file(d) for d in sorted(rest, key=lambda d: d.path)],
            )
        )
    return groups


def hunk_text(diff: Sequence[FileDiff], path: str, line: int | None, max_chars: int = 4000) -> str:
    """The patch hunk containing ``line`` (new side) in ``path``, or the start of the patch."""
    for d in diff:
        if d.path != path:
            continue
        if line is not None:
            for h in d.hunks:
                if h.new_start <= line <= h.new_start + max(h.new_count - 1, 0):
                    body = "\n".join(
                        ("+" if ln.kind == "add" else "-" if ln.kind == "del" else " ") + ln.text
                        for ln in h.lines
                    )
                    head = f"@@ -{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@"
                    head = f"{head} {h.header}".rstrip()
                    return f"{head}\n{body}"[:max_chars]
        return (d.patch or "")[:max_chars]
    return ""
