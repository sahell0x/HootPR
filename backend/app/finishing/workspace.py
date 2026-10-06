"""Sandbox operations of the code-change agent (spec §10.1).

Everything here runs *inside* the sandbox through ``Sandbox.exec``/``shell``: detecting the
project's install/test commands, installing dependencies with the network reconnected (then
re-sealed), running tests with a hard timeout, applying review suggestions, merging the base
branch, and turning the working tree into a change set the worker pushes (never the sandbox).
"""

from __future__ import annotations

import base64
import json
import math
import posixpath
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from app.platforms.finishing import FileChange
from app.sandbox.base import ExecResult, Sandbox, SandboxError, UnsafePath, safe_relpath

GIT_TIMEOUT_S = 120
WRITE_CHUNK = 60_000  # base64 chars per argv element (Linux caps one argument at 128 KiB)
TEST_LOG_TAIL = 12_000
BOT_NAME = "HootPR"
BOT_EMAIL = "hootpr@users.noreply.local"
JUNK_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".gradle",
        ".next",
        ".turbo",
        ".cache",
        "coverage",
        "htmlcov",
        ".hootpr",
    }
)
JUNK_SUFFIXES = (".pyc", ".pyo", ".class", ".o", ".so", ".dylib", ".log")
JUNK_NAMES = frozenset({".coverage", "coverage.xml", ".DS_Store"})
TestStatus = Literal["passed", "failed", "timeout", "oom", "error"]


class ChangeSetError(SandboxError):
    """The change set cannot be pushed (too many / too large files)."""


# --- pure helpers (unit tested) --------------------------------------------------------------


def is_junk(path: str) -> bool:
    """Build/test by-products an untracked file must never be committed as."""
    p = PurePosixPath(path)
    return (
        any(part in JUNK_DIRS for part in p.parts[:-1])
        or p.name in JUNK_NAMES
        or p.name.endswith(JUNK_SUFFIXES)
        or ".egg-info" in path
    )


def parse_porcelain_z(out: str) -> list[tuple[str, str]]:
    """``git status --porcelain=v1 -z`` → ``[(XY, path)]`` (rename sources are dropped)."""
    tokens = out.split("\0")
    items: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if len(tok) < 4:
            continue
        xy, path = tok[:2], tok[3:]
        items.append((xy, path))
        if xy[0] in "RC":
            i += 1  # the next token is the original path
    return items


def parse_name_status_z(out: str) -> list[tuple[str, str]]:
    """``git diff --name-status -z`` → ``[(status letter, path)]``."""
    tokens = [t for t in out.split("\0")]
    items: list[tuple[str, str]] = []
    i = 0
    while i + 1 < len(tokens):
        status = tokens[i]
        if not status:
            i += 1
            continue
        letter = status[0]
        if letter in "RC" and i + 2 < len(tokens):
            items.append(("D" if letter == "R" else "M", tokens[i + 1]))
            items.append(("A", tokens[i + 2]))
            i += 3
            continue
        items.append((letter, tokens[i + 1]))
        i += 2
    return items


def splice_lines(text: str, start: int, end: int, replacement: str) -> str:
    """Replace 1-based inclusive lines ``start..end`` of ``text`` with ``replacement``."""
    lines = text.splitlines(keepends=True)
    if not (1 <= start <= end <= len(lines)):
        raise ValueError(f"lines {start}-{end} outside 1-{len(lines)}")
    new = replacement
    if new and not new.endswith("\n") and (end < len(lines) or lines[end - 1].endswith("\n")):
        new += "\n"
    return "".join(lines[: start - 1]) + new + "".join(lines[end:])


@dataclass(frozen=True)
class SuggestionEdit:
    path: str
    start: int
    end: int
    replacement: str
    ref: str  # finding id


def plan_edits(
    edits: Iterable[SuggestionEdit],
) -> tuple[list[SuggestionEdit], list[SuggestionEdit]]:
    """Non-overlapping edits per file, bottom-up (so earlier line numbers stay valid), and the
    overlapping ones that were skipped."""
    by_path: dict[str, list[SuggestionEdit]] = {}
    for e in edits:
        by_path.setdefault(e.path, []).append(e)
    accepted: list[SuggestionEdit] = []
    skipped: list[SuggestionEdit] = []
    for path in sorted(by_path):
        floor: int | None = None
        for e in sorted(by_path[path], key=lambda x: (x.start, x.end), reverse=True):
            if e.start > e.end or e.start < 1 or (floor is not None and e.end >= floor):
                skipped.append(e)
                continue
            accepted.append(e)
            floor = e.start
    return accepted, skipped


@dataclass(frozen=True)
class Project:
    languages: tuple[str, ...] = ()
    install: tuple[str, ...] = ()
    test: str | None = None


_PY_REQS = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements_dev.txt",
    "requirements-test.txt",
    "requirements_test.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
)


def plan_project(files: set[str], package_json: dict[str, object] | None, work: str) -> Project:
    """Install and test commands for the repository's root project (Python, Node, Go)."""
    langs: list[str] = []
    install: list[str] = []
    tests: list[str] = []
    venv = shlex.quote(f"{work}/.venv")
    has_py_project = bool({"pyproject.toml", "setup.py", "setup.cfg"} & files)
    reqs = [r for r in _PY_REQS if r in files]
    # Loose .py files count too: a script repo with no packaging still runs under pytest.
    if has_py_project or reqs or any(f.endswith(".py") for f in files):
        langs.append("python")
        steps = [f"python3 -m venv {venv}"]
        steps += [f"python -m pip install -q -r {shlex.quote(r)}" for r in reqs]
        if has_py_project:
            steps.append(
                "(python -m pip install -q -e '.[test]' || python -m pip install -q -e '.[dev]' "
                "|| python -m pip install -q -e .)"
            )
        steps.append("python -m pip install -q pytest")
        install.append(" && ".join(steps))
        py_tests = any(
            PurePosixPath(f).name.startswith("test_")
            or PurePosixPath(f).name.endswith("_test.py")
            or f.startswith(("tests/", "test/"))
            for f in files
            if f.endswith(".py")
        )
        if py_tests:
            tests.append("python -m pytest -q -x -p no:cacheprovider")
    if package_json is not None:
        langs.append("node")
        if "pnpm-lock.yaml" in files:
            pm, inst = "corepack pnpm", "corepack pnpm install --frozen-lockfile"
        elif "yarn.lock" in files:
            pm, inst = "corepack yarn", "corepack yarn install --frozen-lockfile"
        elif "package-lock.json" in files:
            pm, inst = "npm", "npm ci --no-audit --no-fund"
        else:
            pm, inst = "npm", "npm install --no-audit --no-fund"
        install.append(inst)
        scripts = package_json.get("scripts")
        test_script = scripts.get("test") if isinstance(scripts, dict) else None
        if isinstance(test_script, str) and "no test specified" not in test_script:
            tests.append(f"{pm} test")
    if "go.mod" in files:
        langs.append("go")
        install.append("go mod download")
        if any(f.endswith("_test.go") for f in files):
            tests.append("go test ./...")
    return Project(tuple(langs), tuple(install), " && ".join(tests) if tests else None)


def work_dir(sb: Sandbox) -> str:
    return posixpath.dirname(sb.repo_dir.rstrip("/"))


def env_prefix(work: str) -> str:
    """Caches and HOME live on the /work volume (HOME=/tmp is a 64 MB tmpfs); the venv is on
    PATH; CI=true keeps test runners out of watch mode."""
    w = shlex.quote(work)
    return (
        f"mkdir -p {w}/.home {w}/.hootpr && "
        f"export HOME={w}/.home COREPACK_HOME={w}/.corepack npm_config_cache={w}/.npm "
        f"npm_config_update_notifier=false GOPATH={w}/.go GOCACHE={w}/.gocache "
        "PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 "
        f"CI=true COREPACK_ENABLE_DOWNLOAD_PROMPT=0 PATH={w}/.venv/bin:$PATH && "
    )


# --- sandbox operations ----------------------------------------------------------------------


def git(sb: Sandbox, *args: str, timeout_s: int = GIT_TIMEOUT_S, max_kb: int = 256) -> ExecResult:
    return sb.exec(["git", *args], timeout_s=timeout_s, max_output_kb=max_kb)


def configure_git(sb: Sandbox) -> None:
    for key, value in (
        ("user.name", BOT_NAME),
        ("user.email", BOT_EMAIL),
        ("commit.gpgsign", "false"),
        ("merge.conflictstyle", "diff3"),
        ("core.hooksPath", "/dev/null"),
    ):
        git(sb, "config", key, value, timeout_s=10)


def detect_project(sb: Sandbox) -> Project:
    # Untracked files too, so a re-detect sees tests the agent just wrote.
    r = git(sb, "ls-files", "-z", "--cached", "--others", "--exclude-standard", max_kb=1024)
    files = {f for f in r.stdout.split("\0") if f} if r.ok else set()
    pkg: dict[str, object] | None = None
    if "package.json" in files:
        try:
            raw = json.loads(sb.read_file("package.json", max_kb=256) or "{}")
            pkg = raw if isinstance(raw, dict) else {}
        except ValueError:
            pkg = {}
    return plan_project(files, pkg, work_dir(sb))


@dataclass(frozen=True)
class StepResult:
    status: Literal["ok", "failed", "timeout", "oom", "unavailable", "skipped"]
    detail: str = ""


def _classify(r: ExecResult, timeout_s: int) -> Literal["ok", "failed", "timeout", "oom"]:
    if r.ok:
        return "ok"
    if r.exit_code == 137 and r.duration_ms < timeout_s * 950:
        return "oom"  # SIGKILL well before the deadline: the memory limit
    if r.timed_out:
        return "timeout"
    return "failed"


def install_dependencies(sb: Sandbox, project: Project, timeout_s: int) -> StepResult:
    """Reconnect the network for the install only, then always seal again (spec §10.1)."""
    if not project.install:
        return StepResult("skipped")
    unseal = getattr(sb, "unseal", None)
    if not callable(unseal):
        return StepResult("unavailable", "this sandbox cannot reconnect its network")
    work = work_dir(sb)
    cmd = (
        env_prefix(work)
        + "{ "
        + " && ".join(f"( {c} )" for c in project.install)
        + f"; }} > {shlex.quote(work)}/.hootpr/install.log 2>&1; c=$?; "
        f"tail -c 4000 {shlex.quote(work)}/.hootpr/install.log; exit $c"
    )
    try:
        unseal()
        r = sb.shell(cmd, timeout_s=timeout_s, max_output_kb=8)
    finally:
        sb.seal()
    status = _classify(r, timeout_s)
    return StepResult(status, (r.stdout + r.stderr)[-4000:])


@dataclass(frozen=True)
class TestRun:
    status: TestStatus
    output: str
    command: str = ""


def run_tests(sb: Sandbox, project: Project, timeout_s: int) -> TestRun:
    """Run the project's tests, sealed, with a hard timeout; the log *tail* is kept (failures
    and summaries are at the end)."""
    if not project.test:
        return TestRun("error", "no test command", "")
    work = shlex.quote(work_dir(sb))
    cmd = (
        env_prefix(work_dir(sb)) + f"( {project.test} ) > {work}/.hootpr/test.log 2>&1; c=$?; "
        f"tail -c {TEST_LOG_TAIL} {work}/.hootpr/test.log; exit $c"
    )
    r = sb.shell(cmd, timeout_s=timeout_s, max_output_kb=16)
    status = _classify(r, timeout_s)
    mapped: TestStatus = "passed" if status == "ok" else status
    return TestRun(mapped, (r.stdout + ("\n" + r.stderr if r.stderr else ""))[-TEST_LOG_TAIL:],
                   project.test)  # fmt: skip


def read_bytes(sb: Sandbox, path: str, max_kb: int) -> bytes:
    rel = safe_relpath(path)
    limit_kb = math.ceil(max_kb * 4 / 3) + 4
    r = sb.exec(["base64", "-w0", "--", f"./{rel}"], timeout_s=30, max_output_kb=limit_kb)
    if not r.ok:
        raise ChangeSetError(f"cannot read {rel}")
    if r.truncated:
        raise ChangeSetError(f"{rel} is larger than {max_kb} KB")
    return base64.b64decode(r.stdout.strip() or "")


def write_bytes(sb: Sandbox, path: str, data: bytes) -> None:
    """Write a repo file (parents created); symlinks are refused."""
    rel = safe_relpath(path)
    probe = sb.exec(["test", "-L", f"./{rel}"], timeout_s=10, max_output_kb=1)
    if probe.exit_code == 0:
        raise UnsafePath(rel)
    encoded = base64.b64encode(data).decode()
    chunks = [encoded[i : i + WRITE_CHUNK] for i in range(0, len(encoded), WRITE_CHUNK)] or [""]
    script = 'mkdir -p -- "$(dirname -- "$2")" && printf %s "$1" | base64 -d {op} "$2"'
    for i, chunk in enumerate(chunks):
        op = ">" if i == 0 else ">>"
        r = sb.exec(
            ["bash", "-c", script.format(op=op), "hootpr-write", chunk, f"./{rel}"],
            timeout_s=30,
            max_output_kb=4,
        )
        if not r.ok:
            raise SandboxError(f"cannot write {rel}: {r.stderr.strip()[:200]}")


def file_unchanged_since(sb: Sandbox, sha: str, path: str) -> bool:
    r = git(sb, "diff", "--quiet", sha, "HEAD", "--", safe_relpath(path), timeout_s=30)
    return r.exit_code == 0


@dataclass
class SuggestionReport:
    applied: list[str] = field(default_factory=list)  # finding ids
    skipped: list[str] = field(default_factory=list)


def apply_suggestions(
    sb: Sandbox, edits: Sequence[SuggestionEdit], anchors: dict[str, str], max_kb: int
) -> SuggestionReport:
    """Apply committable suggestions whose file did not change since their review.

    ``anchors``: finding id → the sha the finding was made at."""
    report = SuggestionReport()
    usable: list[SuggestionEdit] = []
    for e in edits:
        sha = anchors.get(e.ref, "")
        if sha and file_unchanged_since(sb, sha, e.path):
            usable.append(e)
        else:
            report.skipped.append(e.ref)
    accepted, overlapping = plan_edits(usable)
    report.skipped += [e.ref for e in overlapping]
    by_path: dict[str, list[SuggestionEdit]] = {}
    for e in accepted:
        by_path.setdefault(e.path, []).append(e)
    for path, items in by_path.items():
        try:
            text = read_bytes(sb, path, max_kb).decode()
            for e in items:  # already bottom-up
                text = splice_lines(text, e.start, e.end, e.replacement)
            write_bytes(sb, path, text.encode())
            report.applied += [e.ref for e in items]
        except (SandboxError, ValueError, UnicodeDecodeError):
            report.skipped += [e.ref for e in items]
    return report


def resolve_base_tip(sb: Sandbox, base_ref: str) -> str | None:
    """The base branch tip: ``origin/<base>`` (local clones) or the last fetched ref (the
    docker clone fetches ``refs/heads/<base>`` last)."""
    for candidate in (f"refs/remotes/origin/{base_ref}", "FETCH_HEAD"):
        r = git(sb, "rev-parse", "--verify", "-q", f"{candidate}^{{commit}}", timeout_s=10)
        if r.ok and r.stdout.strip():
            return r.stdout.strip()
    return None


@dataclass(frozen=True)
class MergeState:
    conflicted: tuple[str, ...]
    clean: bool
    error: str | None = None


def start_merge(sb: Sandbox, tip: str) -> MergeState:
    r = git(sb, "merge", "--no-commit", "--no-ff", "--no-edit", tip, timeout_s=300)
    if r.ok:
        git(sb, "merge", "--abort", timeout_s=60)
        return MergeState((), True)
    u = git(sb, "diff", "--name-only", "--diff-filter=U", "-z", timeout_s=60)
    conflicted = tuple(p for p in u.stdout.split("\0") if p)
    if not conflicted:
        return MergeState((), False, (r.stderr or r.stdout).strip()[:500] or "merge failed")
    return MergeState(conflicted, False)


def markers_left(sb: Sandbox, paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    r = sb.exec(
        ["grep", "-lE", "^(<<<<<<<|>>>>>>>)( |$)", "--", *[f"./{safe_relpath(p)}" for p in paths]],
        timeout_s=30,
        max_output_kb=64,
    )
    return [line.removeprefix("./") for line in r.stdout.splitlines() if line.strip()]


def collect_changes(
    sb: Sandbox, tree_base: str, *, max_files: int, max_kb: int
) -> list[FileChange]:
    """Stage the agent's edits (by-products of installs/tests excluded) and return the files
    that differ from ``tree_base`` with their new content."""
    st = git(sb, "status", "--porcelain=v1", "-z", "--untracked-files=all", max_kb=2048)
    if not st.ok:
        raise ChangeSetError("git status failed")
    paths = [p for xy, p in parse_porcelain_z(st.stdout) if not (xy == "??" and is_junk(p))]
    for i in range(0, len(paths), 200):
        add = git(sb, "add", "-A", "--", *paths[i : i + 200])
        if not add.ok:
            raise ChangeSetError(f"git add failed: {add.stderr.strip()[:200]}")
    diff = git(
        sb, "diff", "--cached", "--no-renames", "--name-status", "-z", tree_base, max_kb=2048
    )
    if not diff.ok:
        raise ChangeSetError(f"git diff failed: {diff.stderr.strip()[:200]}")
    items = [(s, p) for s, p in parse_name_status_z(diff.stdout) if not (s == "A" and is_junk(p))]
    if len(items) > max_files:
        raise ChangeSetError(f"{len(items)} files changed (limit {max_files})")
    modes: dict[str, str] = {}
    live = [p for s, p in items if s != "D"]
    for i in range(0, len(live), 200):
        ls = git(sb, "ls-files", "-s", "-z", "--", *live[i : i + 200], max_kb=512)
        for entry in ls.stdout.split("\0"):
            meta, _, path = entry.partition("\t")
            if path:
                modes[path] = meta.split(" ", 1)[0]
    out: list[FileChange] = []
    for status, path in items:
        if status == "D":
            out.append(FileChange(path, None))
            continue
        mode = modes.get(path, "100644")
        if mode not in ("100644", "100755"):
            continue  # symlinks / submodules are never pushed
        out.append(
            FileChange(
                path,
                read_bytes(sb, path, max_kb),
                executable=mode == "100755",
                is_new=status == "A",
            )
        )
    return out


def diff_stat(sb: Sandbox, tree_base: str) -> str:
    r = git(sb, "diff", "--cached", "--stat", tree_base, max_kb=16)
    return r.stdout.strip()
