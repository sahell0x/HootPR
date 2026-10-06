"""Fake remote MCP server (streamable HTTP transport) for phase-7 tests."""

from __future__ import annotations

import json
from typing import Any

import httpx

TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_doc",
        "description": "Look up internal API documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
        },
    },
    {
        "name": "delete_everything",
        "description": "Dangerous tool that must never be exposed unless allowlisted.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class FakeMcpServer:
    def __init__(self, *, sse: bool = True, token: str = "secret-token") -> None:
        self.sse, self.token = sse, token
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.session = "sess-123"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def _reply(self, payload: dict[str, Any], *, session: bool = False) -> httpx.Response:
        headers = {"mcp-session-id": self.session} if session else {}
        if self.sse:
            body = f"event: message\ndata: {json.dumps(payload)}\n\n"
            return httpx.Response(
                200, headers={**headers, "content-type": "text/event-stream"}, text=body
            )
        return httpx.Response(200, headers=headers, json=payload)

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        self.headers.append(dict(request.headers))
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        method, rid = body.get("method"), body.get("id")
        if method == "initialize":
            return self._reply(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake", "version": "1"},
                    },
                },
                session=True,
            )
        if request.headers.get("mcp-session-id") != self.session:
            return httpx.Response(400, json={"error": "missing session"})
        if rid is None:  # notification
            return httpx.Response(202)
        if method == "tools/list":
            return self._reply({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        if method == "tools/call":
            name = body["params"]["name"]
            args = body["params"].get("arguments") or {}
            if name == "lookup_doc":
                text = f"Docs for {args.get('topic')}: get_user now requires org_id."
                result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
            else:
                result = {"content": [{"type": "text", "text": "boom"}], "isError": True}
            return self._reply({"jsonrpc": "2.0", "id": rid, "result": result})
        return self._reply(
            {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "not found"}}
        )
