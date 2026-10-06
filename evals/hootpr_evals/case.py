"""Eval case format (spec §14): datasets/cases/<id>/{case.yaml, expected.yaml, base/**, head/**}.

A case is a tiny repository: `base/` is the tree at the base commit, `head/` overlays the files the
"PR" adds or changes, and `case.yaml: deleted` lists files the PR removes. `materialize` turns it into
a real git repo with two commits so the engine can clone it like any PR."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from app.platforms.base import FileDiff, FileStatus
from app.platforms.diff import build_file_diff
from pydantic import BaseModel, ConfigDict, Field, field_validator

DATASETS = Path(__file__).resolve().parents[1] / "datasets" / "cases"
LEARNING_DATASETS = Path(__file__).resolve().parents[1] / "datasets" / "learning_cases"
Category = Literal["bug", "security", "performance", "maintainability", "style", "docs", "test"]
Severity = Literal["critical", "major", "minor", "nitpick"]
# How a team learning changes whether an issue should be reported (learnings suite, phase-3 E1):
# none = always, suppress = only without the learning, require = only with it.
LearningEffect = Literal["none", "suppress", "require"]
# Fixed identity and dates make the two commits (and therefore their SHAs) reproducible; the user's
# global/system git config (signing, hooks, templates) must never influence a materialized case.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "HootPR Evals",
    "GIT_AUTHOR_EMAIL": "evals@hootpr.invalid",
    "GIT_COMMITTER_NAME": "HootPR Evals",
    "GIT_COMMITTER_EMAIL": "evals@hootpr.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}
STATUS: dict[str, FileStatus] = {"A": "added", "M": "modified", "D": "removed", "R": "renamed"}


class ExpectedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str
    line_range: tuple[int, int]
    category: Category
    severity: Severity
    description: str
    learning_effect: LearningEffect = "none"

    @field_validator("line_range")
    @classmethod
    def _ordered(cls, v: tuple[int, int]) -> tuple[int, int]:
        if v[0] < 1 or v[1] < v[0]:
            raise ValueError("line_range must be [start, end] with 1 <= start <= end")
        return v


class CaseMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    language: Literal["python", "typescript", "go"]
    kind: Literal["injected", "cve_reversed", "clean"]
    title: str
    description: str = ""
    source: str = "hand-written"
    deleted: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)  # .hootpr.yaml overrides for this case


class LearningEntry(BaseModel):
    """One team learning seeded before the second review pass (`learnings.yaml`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str = Field(min_length=1)
    scope: Literal["repo", "org"] = "repo"
    path_glob: str | None = None


class _LearningsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    learnings: list[LearningEntry] = Field(default_factory=list)


@dataclass(frozen=True)
class Case:
    meta: CaseMeta
    issues: tuple[ExpectedIssue, ...]
    dir: Path
    learnings: tuple[LearningEntry, ...] = ()

    @property
    def id(self) -> str:
        return self.meta.id


@dataclass(frozen=True)
class Materialized:
    path: Path
    base_sha: str
    head_sha: str
    files: list[FileDiff]


def load_case(d: Path) -> Case:
    meta = CaseMeta.model_validate(yaml.safe_load((d / "case.yaml").read_text()))
    if meta.id != d.name:
        raise ValueError(f"case id {meta.id!r} must equal its directory name {d.name!r}")
    expected = d / "expected.yaml"
    raw = (yaml.safe_load(expected.read_text()) if expected.is_file() else None) or {}
    issues = tuple(ExpectedIssue.model_validate(i) for i in raw.get("issues") or [])
    ids = [i.id for i in issues]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{meta.id}: duplicate issue ids in expected.yaml")
    learnings_file = d / "learnings.yaml"
    learnings: tuple[LearningEntry, ...] = ()
    if learnings_file.is_file():
        parsed = _LearningsFile.model_validate(yaml.safe_load(learnings_file.read_text()) or {})
        learnings = tuple(parsed.learnings)
    return Case(meta, issues, d, learnings)


def load_cases(root: Path = DATASETS, only: Sequence[str] | None = None) -> list[Case]:
    cases = [load_case(d) for d in sorted(root.iterdir()) if (d / "case.yaml").is_file()]
    if only:
        known = {c.id for c in cases}
        missing = [o for o in only if o not in known]
        if missing:
            raise ValueError(f"unknown case(s): {', '.join(missing)}")
        wanted = set(only)
        cases = [c for c in cases if c.id in wanted]
    return cases


def load_learning_cases(root: Path = LEARNING_DATASETS, only: Sequence[str] | None = None) -> list[Case]:
    """Learnings-suite cases: each needs >= 1 learning and >= 1 issue the learning affects."""
    cases = load_cases(root, only)
    for c in cases:
        if not c.learnings:
            raise ValueError(f"{c.id}: a learning case needs at least one learning in learnings.yaml")
        if not any(i.learning_effect != "none" for i in c.issues):
            raise ValueError(f"{c.id}: a learning case needs an issue with learning_effect suppress or require")
    return cases


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    ).stdout


def _diff_files(repo: Path, base: str, head: str) -> list[FileDiff]:
    out: list[FileDiff] = []
    for line in _git(repo, "diff", "--name-status", "-M", base, head).splitlines():
        parts = line.split("\t")
        code, path = parts[0][0], parts[-1]
        old = parts[1] if code == "R" else None
        raw = _git(repo, "diff", "-M", "-U3", "--no-color", base, head, "--", *(p for p in (old, path) if p))
        patch = raw[raw.find("@@") :] if "@@" in raw else ""
        out.append(build_file_diff(path, patch or None, STATUS.get(code, "modified"), old))
    return out


def materialize(case: Case, workdir: Path) -> Materialized:
    repo = workdir / case.id
    if repo.exists():
        shutil.rmtree(repo)
    base_dir = case.dir / "base"
    if base_dir.is_dir():
        shutil.copytree(base_dir, repo)
    else:
        repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", f"base: {case.id}")
    base = _git(repo, "rev-parse", "HEAD").strip()
    if (case.dir / "head").is_dir():
        shutil.copytree(case.dir / "head", repo, dirs_exist_ok=True)
    for rel in case.meta.deleted:
        (repo / rel).unlink(missing_ok=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", case.meta.title)
    head = _git(repo, "rev-parse", "HEAD").strip()
    return Materialized(repo, base, head, _diff_files(repo, base, head))


def _hunk_lines(f: FileDiff) -> list[set[int]]:
    return [{ln.new_line for ln in h.lines if ln.new_line is not None} for h in f.hunks]


def validate_case(case: Case, mat: Materialized) -> list[str]:
    errors: list[str] = []
    if case.meta.kind == "clean" and case.issues:
        errors.append(f"{case.id}: clean cases must not list issues")
    if case.meta.kind != "clean" and not case.issues:
        errors.append(f"{case.id}: non-clean cases need at least one issue")
    files = {f.path: f for f in mat.files}
    if not files:
        errors.append(f"{case.id}: the head commit changes nothing")
    for issue in case.issues:
        f = files.get(issue.path)
        if f is None:
            errors.append(f"{case.id}/{issue.id}: {issue.path} is not in the diff")
            continue
        wanted = set(range(issue.line_range[0], issue.line_range[1] + 1))
        if not any(wanted <= lines for lines in _hunk_lines(f)):
            errors.append(
                f"{case.id}/{issue.id}: lines {issue.line_range} are not inside a single hunk "
                "(new side) — HootPR can only comment on changed hunks"
            )
    return errors
