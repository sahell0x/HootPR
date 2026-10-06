"""The LangGraph self-repair loops: every exit of the test ↔ agent and marker ↔ agent cycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from app.finishing import repair
from app.finishing.agent import CodeChangeAgent, RoundResult
from app.finishing.repair import (
    MarkerRepairContext,
    repair_conflict_markers,
    repair_until_tests_pass,
)
from app.finishing.repair import (
    TestRepairContext as RepairCtx,
)
from app.finishing.workspace import (
    Project,
    configure_git,
    resolve_base_tip,
    start_merge,
    write_bytes,
)
from app.finishing.workspace import TestRun as Run
from app.platforms.base import CloneCredentials
from app.sandbox.base import Sandbox
from app.sandbox.local import LocalSandboxManager
from tests.helpers_git import git, make_git_repo


@dataclass
class FakeAgent:
    edits: list[int]
    prompts: list[str] = field(default_factory=list)

    def feedback(self, text: str) -> RoundResult:
        self.prompts.append(text)
        return RoundResult(f"round {len(self.prompts)}", 3, self.edits.pop(0), "done")


def _tests(monkeypatch: pytest.MonkeyPatch, *statuses: str) -> list[str]:
    queue = list(statuses)

    def fake(sb: Any, project: Any, timeout_s: int) -> Run:
        status = queue.pop(0)
        return Run(status, f"log:{status}")  # type: ignore[arg-type]

    monkeypatch.setattr(repair, "run_tests", fake)
    return queue


def _ctx(agent: FakeAgent, max_iterations: int = 3) -> RepairCtx:
    return RepairCtx(
        cast(Sandbox, None), cast(CodeChangeAgent, agent), Project(test="pytest"), 60,
        max_iterations,
    )  # fmt: skip


def test_passes_first_time(monkeypatch: pytest.MonkeyPatch) -> None:
    _tests(monkeypatch, "passed")
    agent = FakeAgent([])
    assert repair_until_tests_pass(_ctx(agent), "s") == ("verified", "", "s")
    assert agent.prompts == []


def test_fixes_then_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    left = _tests(monkeypatch, "failed", "passed")
    agent = FakeAgent([2])
    assert repair_until_tests_pass(_ctx(agent), "s") == ("verified", "", "round 1")
    assert left == [] and "attempt 1 of 3" in agent.prompts[0]


def test_gives_up_after_max_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    _tests(monkeypatch, "failed", "failed", "failed")
    agent = FakeAgent([1, 1])
    assert repair_until_tests_pass(_ctx(agent), "s") == ("failed", "log:failed", "round 2")
    assert len(agent.prompts) == 2


def test_stops_when_agent_makes_no_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    left = _tests(monkeypatch, "failed", "passed")
    agent = FakeAgent([0])
    verification, _, _ = repair_until_tests_pass(_ctx(agent), "s")
    assert verification == "failed" and left == ["passed"]


def test_infra_error_is_couldnt_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    _tests(monkeypatch, "failed", "oom")
    out = repair_until_tests_pass(_ctx(FakeAgent([1])), "s")
    assert out[0] == "couldnt_verify" and out[1].startswith("the test run ran out of memory")


def test_max_iterations_at_settings_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    _tests(monkeypatch, *["failed"] * 5)
    verification, _, _ = repair_until_tests_pass(_ctx(FakeAgent([1] * 4), 5), "s")
    assert verification == "failed"  # within the recursion limit


def _markers(monkeypatch: pytest.MonkeyPatch, *results: list[str]) -> None:
    queue = list(results)
    monkeypatch.setattr(repair, "markers_left", lambda sb, paths: queue.pop(0))


def _mctx(agent: FakeAgent) -> MarkerRepairContext:
    return MarkerRepairContext(cast(Sandbox, None), cast(CodeChangeAgent, agent), ("a.py",), 2)


def test_markers_resolved_after_one_round(monkeypatch: pytest.MonkeyPatch) -> None:
    _markers(monkeypatch, ["a.py"], [])
    agent = FakeAgent([1])
    assert repair_conflict_markers(_mctx(agent), "s") == ([], "round 1")


def test_markers_left_after_max_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    _markers(monkeypatch, ["a.py"], ["a.py"], ["a.py"])
    agent = FakeAgent([1, 1])
    assert repair_conflict_markers(_mctx(agent), "s") == (["a.py"], "round 2")
    assert len(agent.prompts) == 2


def test_markers_loop_on_a_real_merge_conflict(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, {"f.txt": "one\n"}, {"g.txt": "g\n"})
    git(repo.path, "checkout", "-q", "-b", "feature")
    (repo.path / "f.txt").write_text("feature\n")
    git(repo.path, "commit", "-qam", "feature")
    head = git(repo.path, "rev-parse", "HEAD").strip()
    git(repo.path, "checkout", "-q", "main")
    (repo.path / "f.txt").write_text("main\n")
    git(repo.path, "commit", "-qam", "main")
    sb = LocalSandboxManager().create("ft-test", mem_mb=512, cpus=1.0)
    try:
        sb.clone(CloneCredentials(url=f"file://{repo.path}", username="l", token=""), head, 50)
        sb.seal()
        configure_git(sb)
        tip = resolve_base_tip(sb, "main")
        assert tip is not None
        state = start_merge(sb, tip)
        assert state.conflicted == ("f.txt",)

        class Resolver(FakeAgent):
            def feedback(self, text: str) -> RoundResult:
                if len(self.prompts) == 1:  # resolves on the second round
                    write_bytes(sb, "f.txt", b"feature and main\n")
                return super().feedback(text)

        agent = Resolver([1, 1])
        ctx = MarkerRepairContext(sb, cast(CodeChangeAgent, agent), state.conflicted, 2)
        assert repair_conflict_markers(ctx, "s") == ([], "round 2")
        assert "f.txt" in agent.prompts[0]
    finally:
        sb.destroy()
