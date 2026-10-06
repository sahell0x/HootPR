"""The code-change agent loop with a scripted model and a real (local) checkout."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config.schema import HootPRConfig
from app.finishing.agent import CodeAgentLimits, CodeChangeAgent
from app.finishing.workspace import configure_git
from app.llm.types import LLMResult, Message, ToolCall, TraceContext, Usage
from app.platforms.base import CloneCredentials
from app.sandbox.local import LocalSandboxManager
from tests.helpers_git import make_git_repo


class ScriptedLLM:
    def __init__(self, turns: list[list[tuple[str, dict[str, Any]]]]) -> None:
        self.turns, self.seen = turns, []  # type: list[list[Message]]

    def complete(self, role: str, messages: list[Message], **_: Any) -> LLMResult:
        self.seen.append(list(messages))
        calls = self.turns.pop(0) if self.turns else [("done", {"summary": "-"})]
        return LLMResult(
            None,
            None,
            [ToolCall(f"c{i}", n, json.dumps(a)) for i, (n, a) in enumerate(calls)],
            Usage(100, 0, 10),
            Decimal(0),
            "m",
            None,
            1,
        )


def test_agent_edits_patches_and_blocks_git_dir(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, {"a.py": "x = 1\ny = 2\n"}, {"a.py": "x = 1\ny = 3\n"})
    sb = LocalSandboxManager().create("ft", mem_mb=512, cpus=1.0)
    try:
        sb.clone(CloneCredentials(f"file://{repo.path}", "local", ""), repo.head_sha, 10)
        configure_git(sb)
        patch = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-x = 1\n+x = 10\n y = 3\n"
        llm = ScriptedLLM(
            [
                [("write_file", {"path": "tests/test_a.py", "content": "def test(): pass\n"})],
                [("apply_patch", {"patch": patch})],
                [("write_file", {"path": ".git/config", "content": "evil"})],
                [("done", {"summary": "- added a test"})],
            ]
        )
        agent = CodeChangeAgent(
            llm, sb, HootPRConfig(), CodeAgentLimits(10, 50_000, 1_000_000, False), TraceContext()
        )
        rnd = agent.start("do it")
        assert rnd.stop_reason == "done" and rnd.summary == "- added a test" and rnd.edits == 2
        assert sb.read_file("a.py") == "x = 10\ny = 3\n"
        assert sb.read_file("tests/test_a.py") == "def test(): pass\n"
        last_tool = [m for m in llm.seen[-1] if m.get("role") == "tool"][-1]
        assert last_tool["content"].startswith("error: path must be")
        # shell is not offered on the local backend
        assert all(t["function"]["name"] != "shell" for t in agent._specs)
    finally:
        sb.destroy()
