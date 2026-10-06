"""Stage-aware fake OpenAI-compatible server for engine tests (plan contract C3)."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import httpx

from app.llm.gateway import LLMGateway
from app.llm.metering import InMemoryRecorder
from app.llm.types import Role, RoleConfig
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.kv import DictKV

STAGES = ("TriageResult", "ReviewPlan", "SinglePassFindings", "JudgeBatch", "WalkthroughSummary")
FILE_RE = re.compile(r"^### FILE (\S+)(?: \[(deep|light)\])?\s*$", re.M)
FINDING_RE = re.compile(r"^### FINDING (\d+)\s*$", re.M)
DEFAULT_FINDING: dict[str, Any] = {
    "path": "a.py",
    "start_line": None,
    "end_line": 1,
    "severity": "major",
    "category": "bug",
    "title": "Issue",
    "body": "Explain the issue.",
    "suggestion": None,
    "evidence": [],
    "confidence": 0.9,
}


def stage_of(body: dict[str, Any]) -> str | None:
    rf = body.get("response_format") or {}
    name = (rf.get("json_schema") or {}).get("name")
    if name:
        return str(name)
    for m in body.get("messages", []):
        content = m.get("content")
        if m.get("role") == "system" and isinstance(content, str):
            for s in STAGES:
                if f'"title":"{s}"' in content:
                    return s
    for m in body.get("messages", []):
        content = m.get("content")
        if m.get("role") == "system" and isinstance(content, str):
            if content.startswith("[hootpr:chat]"):
                return "chat"
            break
    return "agent" if body.get("tools") else None


def tool_call(name: str, args: dict[str, Any], i: int = 0) -> dict[str, Any]:
    return {
        "id": f"call_{name}_{i}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def finding(**kw: Any) -> dict[str, Any]:
    return {**DEFAULT_FINDING, **kw}


def report_call(i: int = 0, **kw: Any) -> dict[str, Any]:
    return tool_call("report_finding", finding(**kw), i)


def done_call(summary: str = "checked") -> dict[str, Any]:
    return tool_call("done", {"summary": summary}, 999)


class EngineFakeLLM(FakeLLM):
    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.findings: list[dict[str, Any]] = []
        self.agent_turns: list[list[dict[str, Any]]] | None = None
        self.judge_drop: set[int] = set()
        self.judge_duplicates: dict[int, int] = {}
        self.fail_stages: set[str] = set()
        self.summary: dict[str, Any] | None = None
        self.prompt_tokens = 100
        self.stages: list[str | None] = []
        # finding title -> keyword: the finding is not reported when the prompt's
        # <team_learnings> block mentions the keyword (a learning taught in chat, spec §8).
        self.suppress: dict[str, str] = {}
        self.user_texts: dict[str, list[str]] = {}
        self._turn = 0
        # Chat agent (contract C3): scripted tool-call turns, then ``chat_answer`` as content.
        self.chat_turns: list[list[dict[str, Any]]] | None = None
        self.chat_answer = "Here is the answer."
        self._chat_turn = 0

    def _wanted(self, user: str) -> list[dict[str, Any]]:
        start = user.find("<team_learnings>")
        block = user[start : user.find("</team_learnings>", start) + 1] if start >= 0 else ""
        return [
            f
            for f in self.findings
            if not (
                block
                and f.get("title") in self.suppress
                and self.suppress[str(f["title"])].lower() in block.lower()
            )
        ]

    @staticmethod
    def _user_text(body: dict[str, Any]) -> str:
        return "\n".join(
            str(m.get("content") or "") for m in body.get("messages", []) if m.get("role") == "user"
        )

    def _answer(
        self, stage: str | None, body: dict[str, Any]
    ) -> tuple[str | None, list[dict[str, Any]] | None]:
        if stage in self.fail_stages:
            return "this is not json", None
        user = self._user_text(body)
        if stage == "chat":
            if body.get("tools") and self.chat_turns and self._chat_turn < len(self.chat_turns):
                calls = self.chat_turns[self._chat_turn]
                self._chat_turn += 1
                return None, calls
            return self.chat_answer, None
        if stage == "TriageResult":
            files = [
                {"path": p, "decision": "deep", "summary": f"Changes {p}"}
                for p, _ in FILE_RE.findall(user)
            ]
            return json.dumps({"files": files}), None
        if stage == "ReviewPlan":
            deep = [p for p, kind in FILE_RE.findall(user) if kind != "light"]
            task = {
                "title": "Review changes",
                "files": deep,
                "focus": ["correctness"],
                "rationale": "all deep files",
                "related_symbols": [],
            }
            return json.dumps({"tasks": [task] if deep else []}), None
        if stage == "agent":
            if self.agent_turns is not None:
                calls = (
                    self.agent_turns[self._turn]
                    if self._turn < len(self.agent_turns)
                    else [done_call()]
                )
                self._turn += 1
                return None, calls
            first = not any(m.get("role") == "tool" for m in body.get("messages", []))
            if first:
                return None, [report_call(i, **f) for i, f in enumerate(self._wanted(user))] + [
                    done_call()
                ]
            return None, [done_call()]
        if stage == "SinglePassFindings":
            return json.dumps({"findings": [finding(**f) for f in self._wanted(user)]}), None
        if stage == "JudgeBatch":
            verdicts = [
                {
                    "index": int(i),
                    "verdict": "drop" if int(i) in self.judge_drop else "keep",
                    "reason": "verified" if int(i) not in self.judge_drop else "not a real issue",
                    "adjusted_severity": None,
                    "duplicate_of": self.judge_duplicates.get(int(i)),
                }
                for i in FINDING_RE.findall(user)
            ]
            return json.dumps({"verdicts": verdicts}), None
        if stage == "WalkthroughSummary":
            files = [p for p, _ in FILE_RE.findall(user)]
            return json.dumps(
                self.summary
                or {
                    "walkthrough": "This PR changes things.",
                    "changes": [{"files": files, "summary": "Updated"}],
                    "sequence_diagrams": [],
                    "effort": 2,
                    "effort_minutes": 10,
                    "pr_summary": "- **Bug Fixes**: updated",
                    "poem": None,
                    "title": "Generated title" if "Title requested: yes" in user else None,
                }
            ), None
        return "{}", None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/embeddings") or self.fail_429 or self.fail_500:
            return super().handler(request)
        stage = stage_of(body)
        self.stages.append(stage)
        self.user_texts.setdefault(str(stage), []).append(self._user_text(body))
        content, calls = self._answer(stage, body)
        self.reply(
            content, tool_calls=calls, prompt_tokens=self.prompt_tokens, completion_tokens=20
        )
        resp = super().handler(request)
        if resp.status_code != 200 and self._replies:
            self._replies.pop()  # the capability 400 did not consume our reply
        return resp


def make_test_gateway(fake: FakeLLM) -> tuple[LLMGateway, InMemoryRecorder]:
    rec = InMemoryRecorder()
    roles: dict[Role, RoleConfig] = {
        r: RoleConfig(
            r,
            "http://fake-llm/v1",
            "k",
            f"model-{r}",
            Decimal("0.10"),
            Decimal("0.01"),
            Decimal("0.50"),
        )
        for r in ("review", "cheap", "embed")
    }
    gw = LLMGateway(
        roles, rec, DictKV(), client_factory=lambda cfg: fake.openai_client(), sleep=lambda s: None
    )
    return gw, rec
