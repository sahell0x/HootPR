"""A sandbox that never touches git or Docker: canned build_graph/run_tools output (contract C1)."""

import json
from collections.abc import Sequence
from typing import Any

from app.platforms.base import CloneCredentials
from app.sandbox.base import ExecResult
from tests.helpers_git import EMPTY_GRAPH, EMPTY_TOOLS


class FakeSandbox:
    repo_dir, tools_dir, python = "/work/repo", "/opt/hootpr/tools", "python3"

    def __init__(
        self, graph: dict[str, Any] | None = None, tools: dict[str, Any] | None = None
    ) -> None:
        self.graph, self.tools = graph or EMPTY_GRAPH, tools or EMPTY_TOOLS
        self.calls: list[list[str]] = []
        self.cloned: tuple[str, str] | None = None
        self.sealed = self.destroyed = False

    def clone(
        self, creds: CloneCredentials, ref: str, depth: int, *, extra_refs: Sequence[str] = ()
    ) -> None:
        self.cloned = (creds.url, ref)

    def seal(self) -> None:
        self.sealed = True

    def exec(
        self, argv: list[str], *, timeout_s: int, max_output_kb: int, workdir: str | None = None
    ) -> ExecResult:
        self.calls.append(argv)
        joined = " ".join(argv)
        if "build_graph.py" in joined:
            return ExecResult(0, json.dumps(self.graph), "")
        if "run_tools.py" in joined:
            return ExecResult(0, json.dumps(self.tools), "")
        if argv[:2] == ["du", "-sm"]:
            return ExecResult(0, "1\t/work/repo\n", "")
        return ExecResult(0, "", "")

    def shell(self, cmd: str, *, timeout_s: int, max_output_kb: int) -> ExecResult:
        return self.exec(["bash", "-c", cmd], timeout_s=timeout_s, max_output_kb=max_output_kb)

    def read_file(self, path: str, *, max_kb: int = 512) -> str:
        return ""

    def peak_memory_mb(self) -> int | None:
        return 42

    def destroy(self) -> None:
        self.destroyed = True


class FakeSandboxManager:
    def __init__(
        self, graph: dict[str, Any] | None = None, tools: dict[str, Any] | None = None
    ) -> None:
        self._graph, self._tools = graph, tools
        self.created: list[FakeSandbox] = []

    def create(self, job_id: str, *, mem_mb: int, cpus: float) -> FakeSandbox:
        sb = FakeSandbox(self._graph, self._tools)
        self.created.append(sb)
        return sb
