"""Needs Docker + the hootpr/sandbox image (`make test-sandbox`). The LangGraph test-repair loop
against a real sealed sandbox: real test runs, failure output fed back to a scripted agent."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import docker
import pytest

from app.finishing.agent import CodeChangeAgent, RoundResult
from app.finishing.repair import TestRepairContext as RepairCtx
from app.finishing.repair import repair_until_tests_pass
from app.finishing.workspace import Project, configure_git, write_bytes
from app.platforms.base import CloneCredentials
from app.sandbox.base import Sandbox, sandbox_session
from app.sandbox.docker import DockerSandboxManager
from tests.helpers_git import make_git_repo

pytestmark = pytest.mark.sandbox
IMAGE = os.environ.get("SANDBOX_IMAGE", "hootpr/sandbox:latest")
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = (
    "import unittest\n\nfrom calc import add\n\n\n"
    "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
)
PROJECT = Project(languages=("python",), test="python3 -m unittest -q")


@dataclass
class ScriptedAgent:
    """Applies the next scripted edit (or none) each time it is fed a test failure."""

    sb: Sandbox
    edits: list[bytes | None]
    prompts: list[str] = field(default_factory=list)

    def feedback(self, text: str) -> RoundResult:
        self.prompts.append(text)
        edit = self.edits.pop(0)
        if edit is not None:
            write_bytes(self.sb, "calc.py", edit)
        return RoundResult(f"round {len(self.prompts)}", 2, int(edit is not None), "done")


def _run(tmp_path: Path, edits: list[bytes | None]) -> tuple[tuple[str, str, str], ScriptedAgent]:
    repo = make_git_repo(
        tmp_path / "src", {"calc.py": FIXED}, {"calc.py": BUGGY, "test_calc.py": TEST}
    )
    mgr = DockerSandboxManager(docker.from_env(), image=IMAGE, network="hootpr_sandbox_egress")
    with sandbox_session(mgr, "repair-test", mem_mb=768, cpus=1.0) as sb:
        sb.clone(
            CloneCredentials(url=f"file://{repo.path}", username="l", token=""), repo.head_sha, 50
        )
        sb.seal()
        configure_git(sb)
        agent = ScriptedAgent(sb, edits)
        ctx = RepairCtx(sb, cast(CodeChangeAgent, agent), PROJECT, timeout_s=120, max_iterations=3)
        return repair_until_tests_pass(ctx, "initial"), agent


def test_failure_fed_back_then_verified(tmp_path: Path) -> None:
    (verification, detail, summary), agent = _run(tmp_path, [FIXED.encode()])
    assert (verification, detail, summary) == ("verified", "", "round 1")
    assert len(agent.prompts) == 1
    assert "AssertionError" in agent.prompts[0]  # the real unittest output reached the agent


def test_agent_without_edits_ends_failed_with_real_output(tmp_path: Path) -> None:
    (verification, detail, _), agent = _run(tmp_path, [None])
    assert verification == "failed" and "FAILED (failures=1)" in detail
    assert len(agent.prompts) == 1


def test_gives_up_after_max_iterations(tmp_path: Path) -> None:
    still_buggy = BUGGY.replace("a - b", "a * b").encode()
    (verification, _, summary), agent = _run(tmp_path, [still_buggy, still_buggy])
    assert verification == "failed" and summary == "round 2"
    assert len(agent.prompts) == 2  # 3 test runs, 2 fix rounds in between
