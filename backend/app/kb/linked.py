"""Linked repositories (spec §10.4): shallow clones under ``/work/linked/<name>`` + their graphs.

Clones happen *before* the sandbox is sealed, with the same header-only credential handling as
the main checkout. Every failure degrades (a note in ``degraded``), never fails the review.
"""

from __future__ import annotations

import base64
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from app.logging import get_logger
from app.platforms.base import CloneCredentials, GitPlatform, RepoRef
from app.review.graph import CodeGraph, Symbol
from app.sandbox.base import Sandbox, redact
from app.settings import Settings

log = get_logger(__name__)
CLONE_TIMEOUT_S = 180
GRAPH_MAX_OUTPUT_KB = 8 * 1024
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class LinkedRepoSpec:
    name: str  # directory under /work/linked
    full_name: str
    repo: RepoRef
    instructions: str = ""


def dir_names(full_names: Iterable[str]) -> list[str]:
    """``owner/name`` → ``name`` (``owner-name`` on collision), filesystem-safe."""
    names = list(full_names)
    short = [_NAME_RE.sub("_", n.rsplit("/", 1)[-1]) or "repo" for n in names]
    out: list[str] = []
    for full, s in zip(names, short, strict=True):
        pick = s if short.count(s) == 1 else _NAME_RE.sub("_", full.replace("/", "-"))
        pick = pick.lstrip(".") or "repo"
        while pick in out:
            pick += "_"
        out.append(pick[:100])
    return out


def linked_root(sb: Sandbox) -> str:
    return str(PurePosixPath(sb.repo_dir).parent / "linked")


class LinkedGraph:
    """One linked repository's graph plus its calls to names it does not define."""

    def __init__(
        self,
        spec: LinkedRepoSpec,
        graph: CodeGraph,
        external: dict[str, list[Symbol]],
        *,
        root: str = "",
    ) -> None:
        self.spec, self.graph, self.root = spec, graph, root
        self._external = external

    @classmethod
    def from_json(cls, spec: LinkedRepoSpec, data: Any, *, root: str = "") -> LinkedGraph:
        graph = CodeGraph.from_json(data)
        by_id: dict[str, Symbol] = {}
        raw_syms = data.get("symbols") if isinstance(data, dict) else None
        for raw in raw_syms if isinstance(raw_syms, list) else []:
            try:
                sym = Symbol(
                    str(raw["id"]), str(raw["kind"]), str(raw["name"]),
                    str(raw.get("qualified_name") or raw["name"]), str(raw["path"]),
                    int(raw["start_line"]), int(raw["end_line"]),
                    str(raw.get("signature") or "")[:160],
                )  # fmt: skip
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            by_id[sym.id] = sym
        external: dict[str, list[Symbol]] = defaultdict(list)
        calls = data.get("external_calls") if isinstance(data, dict) else None
        for raw in calls if isinstance(calls, list) else []:
            if not isinstance(raw, dict):
                continue
            caller = by_id.get(str(raw.get("from")))
            name = str(raw.get("name") or "")
            if caller is not None and name:
                external[name].append(caller)
        return cls(spec, graph, dict(external), root=root)

    def callers_of(self, name: str, limit: int = 20) -> list[Symbol]:
        """Symbols in this repo calling ``name`` (bare or qualified) that it does not define."""
        return self._external.get(name.split(".")[-1], [])[:limit]

    def ref(self, s: Symbol) -> str:
        return f"[{self.spec.full_name}] linked/{self.spec.name}/{s.ref()}"


def render_linked_block(graphs: list[LinkedGraph]) -> str:
    if not graphs:
        return ""
    lines = [
        f"- {g.spec.full_name}: checked out at ../linked/{g.spec.name} (relative to the repo root)"
        + (f" — {' '.join(g.spec.instructions.split())[:300]}" if g.spec.instructions else "")
        for g in graphs
    ]
    return (
        "<linked_repositories>\nOther repositories of this organization that may use the code "
        "changed here. `find_callers` also lists their call sites; a change that breaks them is "
        "a cross-repo breaking change.\n" + "\n".join(lines) + "\n</linked_repositories>"
    )


def _clone(sb: Sandbox, creds: CloneCredentials, dest: str) -> str | None:
    """Shallow clone of the default branch into ``dest``; returns an error message or None."""
    work = str(PurePosixPath(dest).parent)
    header: list[str] = []
    auth = ""
    if creds.token:
        auth = base64.b64encode(f"{creds.username}:{creds.token}".encode()).decode()
        header = ["-c", f"http.extraHeader=Authorization: Basic {auth}"]
    steps = [
        ["mkdir", "-p", work],
        ["git", "init", "-q", dest],
        ["git", "-C", dest, *header, "fetch", "-q", "--no-tags", "--depth=1", creds.url, "HEAD"],
        ["git", "-C", dest, "checkout", "-q", "--detach", "FETCH_HEAD"],
    ]
    for argv in steps:
        r = sb.exec(argv, timeout_s=CLONE_TIMEOUT_S, max_output_kb=16, workdir="/")
        if not r.ok:
            return redact(redact(r.stderr.strip(), auth), creds.token)[:300] or "git failed"
    return None


def clone_linked(
    sb: Sandbox,
    platform: GitPlatform,
    specs: Iterable[LinkedRepoSpec],
    settings: Settings,
    degraded: dict[str, Any],
) -> list[LinkedRepoSpec]:
    """Clone each linked repository (call before ``sb.seal()``); returns the ones cloned."""
    root = linked_root(sb)
    done: list[LinkedRepoSpec] = []
    errors: dict[str, str] = {}
    for spec in list(specs)[: settings.linked_repos_max]:
        dest = f"{root}/{spec.name}"
        try:
            creds = platform.clone_credentials(spec.repo)
            err = _clone(sb, creds, dest)
        except Exception as exc:
            err = f"{type(exc).__name__}"
        if err is None:
            size = sb.exec(["du", "-sm", dest], timeout_s=60, max_output_kb=4, workdir="/")
            try:
                mb = int(size.stdout.split()[0])
            except (IndexError, ValueError):
                mb = 0
            if mb > settings.linked_repos_max_mb:
                sb.exec(["rm", "-rf", dest], timeout_s=60, max_output_kb=4, workdir="/")
                err = f"checkout is {mb} MB (limit {settings.linked_repos_max_mb} MB)"
        if err is None:
            done.append(spec)
        else:
            errors[spec.full_name] = err
            log.info("linked_repo_clone_failed", repo=spec.full_name)
    if errors:
        degraded["linked_repositories"] = errors
    return done


def build_linked_graphs(
    sb: Sandbox, specs: Iterable[LinkedRepoSpec], settings: Settings, degraded: dict[str, Any]
) -> list[LinkedGraph]:
    root = linked_root(sb)
    out: list[LinkedGraph] = []
    errors: dict[str, str] = {}
    for spec in specs:
        dest = f"{root}/{spec.name}"
        argv = [
            sb.python, f"{sb.tools_dir}/build_graph.py", "--repo", dest,
            "--max-files", str(settings.graph_max_files),
            "--max-symbols", str(settings.graph_max_symbols),
            "--external-calls",
        ]  # fmt: skip
        r = sb.exec(
            argv,
            timeout_s=settings.sandbox_graph_timeout_s,
            max_output_kb=GRAPH_MAX_OUTPUT_KB,
            workdir=dest,
        )
        data: Any = None
        if r.ok and not r.truncated:
            try:
                data = json.loads(r.stdout)
            except json.JSONDecodeError:
                data = None
        if not isinstance(data, dict):
            errors[spec.full_name] = "graph unavailable"
            continue
        out.append(LinkedGraph.from_json(spec, data, root=dest))
    if errors:
        prev = degraded.get("linked_graphs")
        degraded["linked_graphs"] = {**(prev if isinstance(prev, dict) else {}), **errors}
    return out
