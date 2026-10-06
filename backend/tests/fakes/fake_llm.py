"""Fake OpenAI-compatible server (spec §13): missing json_schema/tools, 429/5xx, bad JSON."""

import json
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx
import openai


def _error(status: int, message: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        json={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": None,
                "code": None,
            }
        },
    )


class FakeLLM:
    def __init__(
        self,
        *,
        json_schema: bool = True,
        json_object: bool = True,
        tools: bool = True,
        max_completion_tokens: bool = True,
        tools_need_no_effort: bool = False,
        fail_429: int = 0,
        fail_500: int = 0,
        dims: int = 8,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self.json_schema, self.json_object, self.tools = json_schema, json_object, tools
        self.max_completion_tokens = max_completion_tokens
        self.tools_need_no_effort = tools_need_no_effort
        self.fail_429, self.fail_500, self.dims = fail_429, fail_500, dims
        self.embed_fn = embed_fn
        self.requests: list[dict[str, Any]] = []
        self._replies: deque[dict[str, Any]] = deque()

    def reply(
        self,
        content: str | None = None,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        prompt_tokens: int = 10,
        cached_tokens: int = 0,
        completion_tokens: int = 5,
    ) -> None:
        self._replies.append(
            {
                "content": content,
                "tool_calls": tool_calls,
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "completion_tokens": completion_tokens,
            }
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append({"path": request.url.path, "body": body})
        if self.fail_429 > 0:
            self.fail_429 -= 1
            return _error(429, "rate limited", {"retry-after": "0"})
        if self.fail_500 > 0:
            self.fail_500 -= 1
            return _error(500, "upstream error")
        if request.url.path.endswith("/embeddings"):
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            data = [
                {
                    "object": "embedding",
                    "index": i,
                    "embedding": (
                        self.embed_fn(str(text))
                        if self.embed_fn is not None
                        else [((i + 1) * (j + 1) % 7) / 7 for j in range(self.dims)]
                    ),
                }
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": data,
                    "model": body["model"],
                    "usage": {"prompt_tokens": 3 * len(inputs), "total_tokens": 3 * len(inputs)},
                },
            )
        rf = body.get("response_format") or {}
        if rf.get("type") == "json_schema" and not self.json_schema:
            return _error(400, "response_format json_schema is not supported by this model")
        if rf.get("type") == "json_object" and not self.json_object:
            return _error(400, "response_format json_object is not supported by this model")
        if (
            body.get("tools")
            and self.tools_need_no_effort
            and body.get("reasoning_effort") != "none"
        ):
            return _error(
                400,
                "Function tools with reasoning_effort are not supported for this model in "
                "/v1/chat/completions. To use function tools, use /v1/responses or set "
                "reasoning_effort to 'none'.",
            )
        if body.get("tools") and not self.tools:
            return _error(400, "tools are not supported by this model")
        if "max_completion_tokens" in body and not self.max_completion_tokens:
            return _error(400, "Unrecognized request argument supplied: max_completion_tokens")
        r = (
            self._replies.popleft()
            if self._replies
            else {
                "content": "{}",
                "tool_calls": None,
                "prompt_tokens": 10,
                "cached_tokens": 0,
                "completion_tokens": 5,
            }
        )
        message: dict[str, Any] = {"role": "assistant", "content": r["content"]}
        if r["tool_calls"]:
            message["tool_calls"] = r["tool_calls"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model", "m"),
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if r["tool_calls"] else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": r["prompt_tokens"],
                    "completion_tokens": r["completion_tokens"],
                    "total_tokens": r["prompt_tokens"] + r["completion_tokens"],
                    "prompt_tokens_details": {"cached_tokens": r["cached_tokens"]},
                },
            },
        )

    def openai_client(self) -> openai.OpenAI:
        return openai.OpenAI(
            base_url="http://fake-llm/v1",
            api_key="test",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )
