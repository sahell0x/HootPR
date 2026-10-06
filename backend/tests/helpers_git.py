"""Temp git repos with real base/head commits, and stub sandbox scripts (contract C1)."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.platforms.base import FileDiff, FileStatus
from app.platforms.diff import build_file_diff

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}
STATUS: dict[str, FileStatus] = {"A": "added", "M": "modified", "D": "removed", "R": "renamed"}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


@dataclass(frozen=True)
class GitRepo:
    path: Path
    base_sha: str
    head_sha: str
    files: list[FileDiff]


def _write(repo: Path, files: dict[str, str | None]) -> None:
    for rel, content in files.items():
        p = repo / rel
        if content is None:
            p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def diff_files(repo: Path, base: str, head: str) -> list[FileDiff]:
    out: list[FileDiff] = []
    for line in git(repo, "diff", "--name-status", "-M", base, head).splitlines():
        parts = line.split("\t")
        code = parts[0][0]
        path = parts[-1]
        old = parts[1] if code == "R" else None
        raw = git(
            repo,
            "diff",
            "-M",
            "-U3",
            "--no-color",
            base,
            head,
            "--",
            *(p for p in (old, path) if p),
        )
        patch = raw[raw.find("@@") :] if "@@" in raw else ""
        out.append(build_file_diff(path, patch or None, STATUS.get(code, "modified"), old))
    return out


def make_git_repo(root: Path, base: dict[str, str], head: dict[str, str | None]) -> GitRepo:
    """A repo at ``root/repo`` with a ``base`` commit and a ``head`` commit (None = delete)."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    _write(repo, dict(base))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD").strip()
    _write(repo, head)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "head")
    head_sha = git(repo, "rev-parse", "HEAD").strip()
    return GitRepo(repo, base_sha, head_sha, diff_files(repo, base_sha, head_sha))


EMPTY_GRAPH: dict[str, Any] = {
    "version": 1,
    "scope": "full",
    "truncated": False,
    "files": [],
    "symbols": [],
    "edges": [],
    "errors": [],
}
EMPTY_TOOLS: dict[str, Any] = {"version": 1, "runs": [], "findings": []}


def write_stub_tools(
    dir: Path, graph: dict[str, Any] | None = None, tools: dict[str, Any] | None = None
) -> Path:
    """Stub build_graph.py / run_tools.py that print canned contract-C1 JSON."""
    dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("build_graph.py", graph or EMPTY_GRAPH),
        ("run_tools.py", tools or EMPTY_TOOLS),
    ):
        (dir / name).write_text(f"import json\nprint(json.dumps({payload!r}))\n")
    return dir
