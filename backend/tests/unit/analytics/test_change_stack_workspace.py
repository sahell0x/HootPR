import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.change_stack.workspace import (
    OTHER_GROUP,
    TaskLike,
    group_files,
    hunk_text,
    language_for,
    pick_snapshot,
    relevant_findings,
    snapshots,
)
from app.platforms.diff import build_file_diff

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def review(sha: str, minutes: int, status: str = "completed") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        head_sha=sha,
        base_sha="b",
        status=status,
        trigger="auto",
        findings_posted=1,
        created_at=T0 + timedelta(minutes=minutes),
    )


def finding(
    path: str, fp: str, line: int = 3, verdict: str | None = "keep", posted: bool = True
) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        path=path,
        fingerprint=fp,
        end_line=line,
        start_line=None,
        severity="major",
        judge_verdict=verdict,
        posted=posted,
    )


def test_snapshots_one_per_sha_with_stale_marker() -> None:
    rs = [review("aaa", 1), review("aaa", 2), review("bbb", 3), review("ccc", 4, "failed")]
    snaps = snapshots(rs, head_sha="bbb")
    assert [s.head_sha for s in snaps] == ["bbb", "aaa"]
    assert [s.stale for s in snaps] == [False, True]
    assert snaps[1].review_id == str(rs[1].id)  # newest review of that sha
    assert pick_snapshot(snaps, None) == snaps[0]
    assert pick_snapshot(snaps, "aa") == snaps[1]
    assert pick_snapshot(snaps, "zzz") is None


def test_relevant_findings_dedupes_and_respects_snapshot_time() -> None:
    r1, r2 = review("a", 1), review("b", 5)
    f_old, f_new = finding("x.py", "fp1"), finding("x.py", "fp1", line=9)
    dropped = finding("y.py", "fp2", verdict="drop", posted=False)
    later = finding("z.py", "fp3")
    rows = [(f_old, r1), (f_new, r2), (dropped, r1), (later, r2)]
    assert relevant_findings(rows, None) == [f_new, later]
    assert relevant_findings(rows, r1.created_at) == [f_old]


def test_group_files_by_task_then_other() -> None:
    patch = "@@ -1,2 +1,3 @@\n a\n+b\n c\n"
    diff = [build_file_diff(p, patch, "modified", None) for p in ("a.py", "b.py", "c.py")]
    tasks = [TaskLike(2, "Second", "", ("b.py", "a.py")), TaskLike(1, "First", "why", ("a.py",))]
    groups = group_files(diff, tasks, [finding("a.py", "f")])
    assert [g.title for g in groups] == ["First", "Second", OTHER_GROUP]
    assert [f.path for f in groups[1].files] == ["b.py"]
    assert groups[0].files[0].findings == 1
    assert group_files(diff, [], [])[0].title == "Changed files"
    assert hunk_text(diff, "a.py", 2).startswith("@@") and "+b" in hunk_text(diff, "a.py", 2)
    assert hunk_text(diff, "nope.py", 1) == ""


def test_language_for() -> None:
    assert language_for("src/app.tsx") == "typescript"
    assert language_for("Dockerfile") == "dockerfile"
    assert language_for("x.unknown") == "plaintext"
