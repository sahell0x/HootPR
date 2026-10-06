from pathlib import Path
from typing import Any

import pytest

from app.config.schema import HootPRConfig
from app.llm.types import ToolsUnsupported, TraceContext
from app.platforms.base import CloneCredentials
from app.review.agent import AgentLimits, Toolbox, run_agent, task_prompt
from app.review.graph import CodeGraph
from app.review.schemas import PlanTask
from app.review.stages.singlepass import single_pass
from app.review.tool_results import ToolResults
from app.sandbox.base import ExecResult, sandbox_session
from app.sandbox.local import LocalSandboxManager
from tests.fakes.engine_llm import (
    EngineFakeLLM,
    done_call,
    make_test_gateway,
    report_call,
    tool_call,
)
from tests.helpers_git import make_git_repo

T = TraceContext()
CFG = HootPRConfig()
TASK = PlanTask(title="Auth", files=["a.py"], focus=["security"], rationale="r", related_symbols=[])
LIM = AgentLimits(max_steps=8, max_input_tokens=60_000)


class FakeSandbox:
    repo_dir, tools_dir, python = "/work/repo", "/opt/hootpr/tools", "python3"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def exec(
        self, argv: list[str], *, timeout_s: int, max_output_kb: int, workdir: str | None = None
    ) -> ExecResult:
        self.calls.append(argv)
        return ExecResult(0, "a.py:3: get_user(uid)\n", "")

    def shell(self, cmd: str, *, timeout_s: int, max_output_kb: int) -> ExecResult:
        return self.exec(["bash", "-c", cmd], timeout_s=timeout_s, max_output_kb=max_output_kb)


def steps_recorder() -> tuple[list[tuple[Any, ...]], Any]:
    rows: list[tuple[Any, ...]] = []
    return rows, lambda *a: rows.append(a)


def test_agent_investigates_reports_and_stops_on_done() -> None:
    fake = EngineFakeLLM()
    fake.agent_turns = [
        [tool_call("shell", {"cmd": "rg get_user"}), report_call(0, path="a.py", end_line=3)],
        [done_call("checked auth")],
    ]
    gw, _ = make_test_gateway(fake)
    sb = FakeSandbox()
    rows, hook = steps_recorder()
    out = run_agent(
        gw,
        TASK,
        0,
        "pack",
        Toolbox(sb, CodeGraph.empty(), ToolResults(), LIM),
        LIM,
        CFG,  # type: ignore[arg-type]
        trace=T,
        on_step=hook,
    )
    assert out.stop_reason == "done" and out.steps == 1 and out.summary == "checked auth"
    assert [(f.path, f.end_line) for f in out.findings] == [("a.py", 3)]
    assert sb.calls == [["bash", "-c", "rg get_user"]]
    assert [r[0] for r in rows] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "final",
    ]


def test_step_budget_forces_stop_but_keeps_findings() -> None:
    fake = EngineFakeLLM()
    fake.agent_turns = [[report_call(0, end_line=2), tool_call("shell", {"cmd": "ls"})]] + [
        [tool_call("shell", {"cmd": "ls"}, i)] for i in range(1, 10)
    ]
    gw, _ = make_test_gateway(fake)
    lim = AgentLimits(max_steps=2, max_input_tokens=60_000)
    out = run_agent(
        gw,
        TASK,
        0,
        "p",
        Toolbox(FakeSandbox(), CodeGraph.empty(), ToolResults(), lim),
        lim,
        CFG,  # type: ignore[arg-type]
        trace=T,
        on_step=lambda *a: None,
    )
    assert out.stop_reason == "step_cap" and out.steps == 2 and len(out.findings) == 1


def test_token_cap_stops_immediately() -> None:
    fake = EngineFakeLLM()
    fake.prompt_tokens = 70_000
    fake.agent_turns = [[tool_call("shell", {"cmd": "ls"})], [done_call()]]
    gw, _ = make_test_gateway(fake)
    out = run_agent(
        gw,
        TASK,
        0,
        "p",
        Toolbox(FakeSandbox(), CodeGraph.empty(), ToolResults(), LIM),
        LIM,
        CFG,  # type: ignore[arg-type]
        trace=T,
        on_step=lambda *a: None,
    )
    assert out.stop_reason == "token_cap"


def test_invalid_finding_is_reported_back_to_the_model() -> None:
    fake = EngineFakeLLM()
    fake.agent_turns = [[report_call(0, severity="huge")], [done_call()]]
    gw, _ = make_test_gateway(fake)
    out = run_agent(
        gw,
        TASK,
        0,
        "p",
        Toolbox(FakeSandbox(), CodeGraph.empty(), ToolResults(), LIM),
        LIM,
        CFG,  # type: ignore[arg-type]
        trace=T,
        on_step=lambda *a: None,
    )
    assert out.findings == []
    tool_msgs = [m for m in fake.requests[-1]["body"]["messages"] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("error: invalid finding")


def test_provider_without_tools_raises_tools_unsupported() -> None:
    gw, _ = make_test_gateway(EngineFakeLLM(tools=False))
    with pytest.raises(ToolsUnsupported):
        run_agent(
            gw,
            TASK,
            0,
            "p",
            Toolbox(FakeSandbox(), CodeGraph.empty(), ToolResults(), LIM),
            LIM,
            CFG,  # type: ignore[arg-type]
            trace=T,
            on_step=lambda *a: None,
        )


def test_read_file_is_numbered_capped_and_confined(tmp_path: Path) -> None:
    repo = make_git_repo(
        tmp_path / "src", {"a.py": "".join(f"l{i}\n" for i in range(1, 1001))}, {"b.py": "x\n"}
    )
    with sandbox_session(LocalSandboxManager(base_dir=tmp_path), "j", mem_mb=768, cpus=1.0) as sb:
        sb.clone(
            CloneCredentials(url=f"file://{repo.path}", username="l", token=""), repo.head_sha, 50
        )
        tb = Toolbox(sb, CodeGraph.empty(), ToolResults(), LIM)
        out = tb.call("read_file", {"path": "a.py", "start": 3, "end": 5000})
        assert "     3  l3" in out and "   402  l402" in out and "l403" not in out
        assert tb.call("read_file", {"path": "../../etc/passwd"}).startswith("error: path")
        assert tb.call("nope", {}).startswith("error: unknown tool")


def test_single_pass_returns_candidates() -> None:
    fake = EngineFakeLLM()
    fake.findings = [{"path": "a.py", "end_line": 4, "title": "Bug"}]
    gw, _ = make_test_gateway(fake)
    out = single_pass(gw, TASK, 0, "p", CFG, trace=T)
    assert [(c.path, c.end_line, c.title) for c in out] == [("a.py", 4, "Bug")]
    assert '<task ordinal="0">' in task_prompt(TASK, 0, "p")


def test_report_finding_tolerates_missing_optional_fields() -> None:
    fake = EngineFakeLLM()
    minimal = {
        "path": "a.py",
        "end_line": 5,
        "severity": "minor",
        "category": "bug",
        "title": "T",
        "body": "B",
        "confidence": 0.8,
    }
    fake.agent_turns = [[tool_call("report_finding", minimal)], [done_call()]]
    gw, _ = make_test_gateway(fake)
    out = run_agent(
        gw,
        TASK,
        0,
        "p",
        Toolbox(FakeSandbox(), CodeGraph.empty(), ToolResults(), LIM),  # type: ignore[arg-type]
        LIM,
        CFG,
        trace=T,
        on_step=lambda *a: None,
    )
    assert [(c.end_line, c.suggestion, c.evidence) for c in out.findings] == [(5, None, [])]


def test_agent_without_sandbox_refuses_shell() -> None:
    tb = Toolbox(None, CodeGraph.empty(), ToolResults(), LIM)
    assert tb.call("shell", {"cmd": "ls"}) == "error: sandbox unavailable"
    assert tb.call("get_tool_findings", {"path": ""}).endswith("no static findings\n</untrusted>")


def _run(fake: EngineFakeLLM, lim: AgentLimits, sb: Any = None) -> Any:
    gw, _ = make_test_gateway(fake)
    return run_agent(
        gw,
        TASK,
        0,
        "p",
        Toolbox(sb or FakeSandbox(), CodeGraph.empty(), ToolResults(), lim),
        lim,
        CFG,
        trace=T,
        on_step=lambda *a: None,
    )


def test_task_input_tokens_are_capped_cumulatively() -> None:
    """Each step resends the transcript: the per-task cap sums input over all calls (§7.5)."""
    fake = EngineFakeLLM()
    fake.prompt_tokens = 30_000
    fake.agent_turns = [[tool_call("shell", {"cmd": "ls"}, i)] for i in range(6)]
    lim = AgentLimits(max_steps=8, max_input_tokens=60_000, max_task_input_tokens=70_000)
    out = _run(fake, lim)
    assert out.stop_reason == "token_cap" and len(fake.requests) == 3


def test_oversized_prompt_is_never_sent() -> None:
    fake = EngineFakeLLM()
    lim = AgentLimits(max_steps=8, max_input_tokens=10)
    out = _run(fake, lim)
    assert out.stop_reason == "token_cap" and fake.requests == []


def test_findings_per_task_are_capped() -> None:
    fake = EngineFakeLLM()
    fake.agent_turns = [
        [report_call(i, path="a.py", end_line=i + 1) for i in range(20)],
        [done_call()],
    ]
    out = _run(fake, AgentLimits(max_steps=8, max_input_tokens=60_000, max_findings=15))
    assert len(out.findings) == 15
    tool_msgs = [m for m in fake.requests[-1]["body"]["messages"] if m["role"] == "tool"]
    assert tool_msgs[-1]["content"].startswith("error: finding budget exhausted")


def test_shell_can_be_disabled_for_host_sandboxes() -> None:
    fake = EngineFakeLLM()
    fake.agent_turns = [[tool_call("shell", {"cmd": "cat ~/.ssh/id_rsa"})], [done_call()]]
    sb = FakeSandbox()
    _run(fake, AgentLimits(max_steps=8, max_input_tokens=60_000, allow_shell=False), sb)
    names = {t["function"]["name"] for t in fake.requests[0]["body"]["tools"]}
    assert "shell" not in names and "read_file" in names
    assert sb.calls == []


def test_sandbox_exceptions_become_tool_errors() -> None:
    class Broken(FakeSandbox):
        def shell(self, cmd: str, *, timeout_s: int, max_output_kb: int) -> ExecResult:
            raise ConnectionError("Read timed out")

    tb = Toolbox(Broken(), CodeGraph.empty(), ToolResults(), LIM)
    assert tb.call("shell", {"cmd": "setsid sleep 9999 &"}) == (
        "error: sandbox command failed (ConnectionError)"
    )


def test_read_file_output_is_capped_and_symlinks_are_refused(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOKEN=abc\n")
    repo = make_git_repo(tmp_path / "src", {"a.py": "x" * 300 + "\n"}, {"b.py": "y\n"})
    with sandbox_session(LocalSandboxManager(base_dir=tmp_path), "j", mem_mb=768, cpus=1.0) as sb:
        sb.clone(
            CloneCredentials(url=f"file://{repo.path}", username="l", token=""), repo.head_sha, 50
        )
        Path(sb.repo_dir, "link.txt").symlink_to(secret)
        lim = AgentLimits(max_steps=8, max_input_tokens=60_000, shell_max_output_kb=0)
        tb = Toolbox(sb, CodeGraph.empty(), ToolResults(), lim)
        assert "[output truncated" in tb.call("read_file", {"path": "a.py", "start": 1, "end": 2})
        tb = Toolbox(sb, CodeGraph.empty(), ToolResults(), LIM)
        assert tb.call("read_file", {"path": "link.txt", "start": 1, "end": 2}).startswith(
            "error: path"
        )
