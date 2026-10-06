"""Workspace operations against a real git checkout (LocalSandbox runs git on the host)."""

from pathlib import Path

import pytest

from app.finishing.workspace import (
    SuggestionEdit,
    apply_suggestions,
    collect_changes,
    configure_git,
    markers_left,
    resolve_base_tip,
    start_merge,
    write_bytes,
)
from app.platforms.base import CloneCredentials
from app.sandbox.base import Sandbox, UnsafePath
from app.sandbox.local import LocalSandboxManager
from tests.helpers_git import git, make_git_repo


def _sandbox(src: Path, ref: str) -> Sandbox:
    sb = LocalSandboxManager().create("ft-test", mem_mb=512, cpus=1.0)
    sb.clone(CloneCredentials(url=f"file://{src}", username="local", token=""), ref, 50)
    sb.seal()
    configure_git(sb)
    return sb


def test_collect_changes_skips_junk_and_reports_new_deleted(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, {"a.py": "x = 1\n", "old.py": "o\n"}, {"a.py": "x = 2\n"})
    sb = _sandbox(repo.path, repo.head_sha)
    try:
        write_bytes(sb, "a.py", b"x = 3\n")
        write_bytes(sb, "tests/test_a.py", b"def test(): pass\n")
        write_bytes(sb, "__pycache__/a.cpython-312.pyc", b"\0junk")
        write_bytes(sb, "node_modules/x/index.js", b"junk")
        sb.exec(["rm", "old.py"], timeout_s=5, max_output_kb=1)
        changes = {c.path: c for c in collect_changes(sb, repo.head_sha, max_files=10, max_kb=64)}
        assert set(changes) == {"a.py", "tests/test_a.py", "old.py"}
        assert changes["a.py"].content == b"x = 3\n" and not changes["a.py"].is_new
        assert changes["tests/test_a.py"].is_new
        assert changes["old.py"].content is None
    finally:
        sb.destroy()


def test_write_bytes_refuses_symlinks_and_escapes(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, {"a.py": "x\n"}, {"a.py": "y\n"})
    sb = _sandbox(repo.path, repo.head_sha)
    try:
        sb.exec(["ln", "-s", "/etc/hostname", "link"], timeout_s=5, max_output_kb=1)
        with pytest.raises(UnsafePath):
            write_bytes(sb, "link", b"pwned")
        with pytest.raises(UnsafePath):
            write_bytes(sb, "../outside.txt", b"pwned")
    finally:
        sb.destroy()


def test_apply_suggestions_only_on_unchanged_files(tmp_path: Path) -> None:
    repo = make_git_repo(
        tmp_path,
        {"a.py": "a = 1\nb = 2\nc = 3\n", "b.py": "q = 1\n"},
        {"a.py": "a = 1\nb = 20\nc = 3\n", "b.py": "q = 2\n"},
    )
    # b.py changes again after the review: its suggestion must be skipped
    git(repo.path, "checkout", "-q", "-b", "later")
    (repo.path / "b.py").write_text("q = 3\n")
    git(repo.path, "commit", "-qam", "later")
    later = git(repo.path, "rev-parse", "HEAD").strip()
    sb = _sandbox(repo.path, later)
    try:
        report = apply_suggestions(
            sb,
            [
                SuggestionEdit("a.py", 2, 2, "b = 2  # fixed", "f1"),
                SuggestionEdit("b.py", 1, 1, "q = 99", "f2"),
            ],
            {"f1": repo.head_sha, "f2": repo.head_sha},
            max_kb=64,
        )
        assert report.applied == ["f1"] and report.skipped == ["f2"]
        assert sb.read_file("a.py") == "a = 1\nb = 2  # fixed\nc = 3\n"
    finally:
        sb.destroy()


def test_merge_conflict_detection_and_markers(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, {"f.txt": "one\n"}, {"g.txt": "g\n"})
    git(repo.path, "checkout", "-q", "-b", "feature")
    (repo.path / "f.txt").write_text("feature\n")
    git(repo.path, "commit", "-qam", "feature")
    head = git(repo.path, "rev-parse", "HEAD").strip()
    git(repo.path, "checkout", "-q", "main")
    (repo.path / "f.txt").write_text("main\n")
    git(repo.path, "commit", "-qam", "main")
    sb = _sandbox(repo.path, head)
    try:
        tip = resolve_base_tip(sb, "main")
        assert tip == git(repo.path, "rev-parse", "main").strip()
        state = start_merge(sb, tip)
        assert state.conflicted == ("f.txt",) and not state.clean
        assert markers_left(sb, ["f.txt"]) == ["f.txt"]
        write_bytes(sb, "f.txt", b"feature and main\n")
        assert markers_left(sb, ["f.txt"]) == []
        changes = collect_changes(sb, head, max_files=10, max_kb=64)
        assert [(c.path, c.content) for c in changes] == [("f.txt", b"feature and main\n")]
    finally:
        sb.destroy()
