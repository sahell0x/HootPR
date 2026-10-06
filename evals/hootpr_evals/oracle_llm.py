"""Oracle OpenAI-compatible fake for one eval case (contract C3). The agent 'finds' exactly the case's
expected issues (plus optional low-confidence noise); every other stage answers deterministically.
Used by tests and `run.py --fake-llm` to prove the pipeline end to end without keys.

Learnings (phase-3 E1): `POST /embeddings` is answered with the hashing embedder, and an issue's
`learning_effect` decides whether the agent / single-pass stages report it — `suppress` only when the
user message has no `<team_learnings>` block, `require` only when it has one, `none` always."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import httpx
import openai

from hootpr_evals.case import ExpectedIssue
from hootpr_evals.embed import hash_embed

STAGES = ("TriageResult", "ReviewPlan", "SinglePassFindings", "JudgeBatch", "WalkthroughSummary", "MatchVerdict")
FILE_RE = re.compile(r"^### FILE (\S+)(?: \[(deep|light)\])?\s*$", re.M)
FINDING_RE = re.compile(r"^### FINDING (\d+)\s*$", re.M)
NOISE_CONFIDENCE = 0.3  # below every profile's keep threshold: the judge must filter it
LEARNINGS_TAG = "<team_learnings>"
CHAT_MARKER = "[hootpr:chat]"
DEFAULT_EMBED_DIMS = 64
CHAT_REPLY = "Thanks, noted. (oracle chat reply)"


def stage_of(body: dict[str, Any]) -> str | None:
    """Which C3 stage a chat-completions request belongs to (None: unknown)."""
    name = ((body.get("response_format") or {}).get("json_schema") or {}).get("name")
    if name:
        return str(name)
    messages = body.get("messages", [])
    first_system = next((m for m in messages if m.get("role") == "system"), None)
    if first_system is not None and _text(first_system.get("content")).startswith(CHAT_MARKER):
        return "chat"
    for m in messages:
        content = m.get("content")
        if m.get("role") == "system" and isinstance(content, str):
            for s in STAGES:
                if f'"title":"{s}"' in content:
                    return s
    return "agent" if body.get("tools") else None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content parts
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return ""


class OracleLLM:
    def __init__(self, issues: Sequence[ExpectedIssue], *, noise: bool = False) -> None:
        self.issues, self.noise = list(issues), noise
        self.stages: list[str] = []

    def _reported(self, user_text: str) -> list[ExpectedIssue]:
        """The issues this oracle reports for a task prompt, after applying `learning_effect`."""
        has_learnings = LEARNINGS_TAG in user_text
        files = {p for p, _ in FILE_RE.findall(user_text)}
        return [
            iss
            for iss in self.issues
            if iss.path in files
            and not (iss.learning_effect == "suppress" and has_learnings)
            and not (iss.learning_effect == "require" and not has_learnings)
        ]

    def agent_titles(self, user_text: str) -> set[str]:
        """Ids of the issues the agent / single-pass stage would report for this user text."""
        return {iss.id for iss in self._reported(user_text)}

    def _findings(self, user_text: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for iss in self._reported(user_text):
            out.append(
                {
                    "path": iss.path,
                    "start_line": iss.line_range[0],
                    "end_line": iss.line_range[1],
                    "severity": iss.severity,
                    "category": iss.category,
                    "title": iss.description[:80],
                    "body": iss.description,
                    "suggestion": None,
                    "evidence": [f"{iss.path}:{iss.line_range[0]}"],
                    "confidence": 0.9,
                }
            )
            if self.noise:
                out.append(
                    {
                        **out[-1],
                        "category": "style",
                        "severity": "nitpick",
                        "title": "Consider renaming",
                        "body": "Naming could be clearer.",
                        "confidence": NOISE_CONFIDENCE,
                    }
                )
        return out

    def _answer(self, stage: str | None, body: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]] | None]:
        messages: list[dict[str, Any]] = body.get("messages", [])
        user = "\n".join(_text(m.get("content")) for m in messages if m.get("role") == "user")
        marked = FILE_RE.findall(user)
        files = list(dict.fromkeys(p for p, _ in marked))
        if stage == "TriageResult":
            triage = [{"path": p, "decision": "deep", "summary": f"Updates {p}"} for p in files]
            return json.dumps({"files": triage}), None
        if stage == "ReviewPlan":
            deep = list(dict.fromkeys(p for p, kind in marked if kind != "light"))
            tasks = (
                [
                    {
                        "title": "Review the change",
                        "files": deep,
                        "focus": ["security", "correctness"],
                        "rationale": "single task",
                        "related_symbols": [],
                    }
                ]
                if deep
                else []
            )
            return json.dumps({"tasks": tasks}), None
        if stage == "chat":
            return CHAT_REPLY, None
        if stage == "agent":
            if any(m.get("role") == "tool" for m in messages):
                return None, [self._call("done", {"summary": "done"}, 99)]
            calls = [self._call("report_finding", f, i) for i, f in enumerate(self._findings(user))]
            return None, [*calls, self._call("done", {"summary": "checked the task files"}, 99)]
        if stage == "SinglePassFindings":
            return json.dumps({"findings": self._findings(user)}), None
        if stage == "JudgeBatch":
            verdicts = [
                {"index": int(i), "verdict": "keep", "reason": "matches the code", "adjusted_severity": None, "duplicate_of": None}
                for i in FINDING_RE.findall(user)
            ]
            return json.dumps({"verdicts": verdicts}), None
        if stage == "WalkthroughSummary":
            summary = {
                "walkthrough": "Eval PR.",
                "changes": [{"files": files, "summary": "Changed."}] if files else [],
                "sequence_diagrams": [],
                "effort": 2,
                "effort_minutes": 10,
                "pr_summary": "- Eval change",
                "poem": None,
            }
            return json.dumps(summary), None
        if stage == "MatchVerdict":
            return json.dumps({"same_issue": True, "reason": "oracle"}), None
        return "{}", None

    @staticmethod
    def _call(name: str, args: dict[str, Any], i: int) -> dict[str, Any]:
        return {"id": f"call_{name}_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    def _embeddings(self, body: dict[str, Any]) -> httpx.Response:
        raw = body.get("input", [])
        texts = [raw] if isinstance(raw, str) else [str(t) for t in raw]
        dims = int(body.get("dimensions") or DEFAULT_EMBED_DIMS)
        vectors = hash_embed(texts, dims=dims)
        tokens = max(1, sum(len(t) for t in texts) // 4)
        # Plain float lists even when the SDK asks for base64: the client passes lists through unchanged.
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"index": i, "embedding": v, "object": "embedding"} for i, v in enumerate(vectors)],
                "model": body.get("model", "oracle-embed"),
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            },
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content or b"{}")
        if request.url.path.endswith("/embeddings"):
            self.stages.append("embeddings")
            return self._embeddings(body)
        stage = stage_of(body)
        self.stages.append(stage or "unknown")
        content, calls = self._answer(stage, body)
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if calls:
            message["tool_calls"] = calls
        prompt = max(1, len(request.content or b"") // 4)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-oracle",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model", "oracle"),
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
                "usage": {
                    "prompt_tokens": prompt,
                    "completion_tokens": 50,
                    "total_tokens": prompt + 50,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
        )

    def client(self) -> openai.OpenAI:
        return openai.OpenAI(
            base_url="http://oracle-llm/v1",
            api_key="oracle",
            max_retries=0,
            # openai types http_client against its vendored httpx alias; the runtime accepts httpx.Client.
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),  # type: ignore[arg-type,unused-ignore]
        )
