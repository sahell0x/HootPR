"""Minimal MCP client over the streamable HTTP transport (spec §10.4).

Only what HootPR needs: ``initialize`` → ``notifications/initialized`` → ``tools/list`` /
``tools/call``. Each request is one JSON-RPC POST whose reply is either ``application/json`` or a
``text/event-stream`` carrying the matching response. stdio servers are never supported: nothing
runs on the host. Calls are made by the worker, never from the sandbox.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.kb.ssrf import Resolver, UnsafeUrl, check_url, is_public_ip

PROTOCOL_VERSION = "2025-06-18"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TOOLS = 100
CLIENT_INFO = {"name": "hootpr", "version": "0.1.0"}


class McpError(Exception):
    """Transport, protocol or server error; the message is safe to show to admins."""


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class McpPolicy:
    allow_http: bool = False
    allow_private: bool = False
    timeout_s: float = 20.0
    resolver: Resolver | None = None


def _sse_messages(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    data: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                msg = json.loads("\n".join(data))
            except json.JSONDecodeError:
                msg = None
            if isinstance(msg, dict):
                out.append(msg)
            data = []
    return out


def render_content(result: dict[str, Any]) -> str:
    """Flatten a ``tools/call`` result's content blocks to text."""
    parts: list[str] = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "resource":
            res = block.get("resource") or {}
            if isinstance(res, dict) and "text" in res:
                parts.append(str(res["text"]))
        else:
            parts.append(f"[{kind} content omitted]")
    if not parts and isinstance(result.get("structuredContent"), dict):
        parts.append(json.dumps(result["structuredContent"])[:20000])
    text = "\n".join(parts)
    return f"error: {text}" if result.get("isError") else text


class McpClient:
    def __init__(
        self,
        url: str,
        headers: dict[str, str],
        policy: McpPolicy,
        *,
        http: httpx.Client | None = None,
    ) -> None:
        self.url = url
        self._headers = dict(headers)
        self._policy = policy
        self._own = http is None
        self._http = http or httpx.Client(timeout=policy.timeout_s, follow_redirects=False)
        self._ids = itertools.count(1)
        self._session: str | None = None
        self._ready = False

    def close(self) -> None:
        if self._own:
            self._http.close()

    def __enter__(self) -> McpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- transport ----------------------------------------------------------------------------
    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            check_url(
                self.url,
                allow_http=self._policy.allow_http,
                allow_private=self._policy.allow_private,
                resolver=self._policy.resolver,
            )
        except UnsafeUrl as exc:
            raise McpError(f"blocked URL: {exc}") from exc
        headers = {
            **self._headers,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        try:
            with self._http.stream(
                "POST",
                self.url,
                json=payload,
                headers=headers,
                timeout=self._policy.timeout_s,
                follow_redirects=False,
            ) as resp:
                self._check_peer(resp)
                body = b""
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise McpError("MCP response too large")
                return httpx.Response(resp.status_code, headers=resp.headers, content=body)
        except httpx.TimeoutException as exc:
            raise McpError("MCP server timed out") from exc
        except httpx.HTTPError as exc:
            raise McpError(f"MCP request failed ({type(exc).__name__})") from exc

    def _check_peer(self, resp: httpx.Response) -> None:
        """DNS-rebinding guard: the address we actually connected to must be public too."""
        if self._policy.allow_private:
            return
        stream = resp.extensions.get("network_stream")
        get = getattr(stream, "get_extra_info", None)
        addr = get("server_addr") if callable(get) else None
        if isinstance(addr, tuple) and addr and not is_public_ip(str(addr[0])):
            raise McpError("blocked URL: connected to a non-public address")

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        rid = next(self._ids)
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        resp = self._post(payload)
        if resp.status_code in (301, 302, 303, 307, 308):
            raise McpError("MCP server redirected; redirects are not followed")
        if resp.status_code == 404 and self._session:
            raise McpError("MCP session expired")
        if resp.status_code in (401, 403):
            raise McpError(f"MCP server rejected the credentials (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise McpError(f"MCP server returned HTTP {resp.status_code}")
        session = resp.headers.get("mcp-session-id")
        if session:
            self._session = session[:256]
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        text = resp.text
        if ctype == "text/event-stream":
            msgs = _sse_messages(text)
        else:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise McpError("MCP server sent invalid JSON") from exc
            msgs = parsed if isinstance(parsed, list) else [parsed]
        for msg in msgs:
            if isinstance(msg, dict) and msg.get("id") == rid:
                if isinstance(msg.get("error"), dict):
                    err = msg["error"]
                    raise McpError(f"MCP error {err.get('code')}: {str(err.get('message'))[:300]}")
                result = msg.get("result")
                if not isinstance(result, dict):
                    raise McpError("MCP response has no result")
                return result
        raise McpError(f"MCP server sent no response to {method}")

    def _notify(self, method: str) -> None:
        resp = self._post({"jsonrpc": "2.0", "method": method})
        if resp.status_code >= 400 and resp.status_code != 405:
            raise McpError(f"MCP server returned HTTP {resp.status_code}")

    # --- protocol -----------------------------------------------------------------------------
    def initialize(self) -> None:
        if self._ready:
            return
        self._rpc(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        self._notify("notifications/initialized")
        self._ready = True

    def list_tools(self) -> list[McpTool]:
        self.initialize()
        tools: list[McpTool] = []
        cursor: str | None = None
        for _ in range(10):  # pagination bound
            res = self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            for raw in res.get("tools") or []:
                if isinstance(raw, dict) and isinstance(raw.get("name"), str):
                    schema = raw.get("inputSchema")
                    tools.append(
                        McpTool(
                            raw["name"][:128],
                            str(raw.get("description") or "")[:1000],
                            schema if isinstance(schema, dict) else {},
                        )
                    )
            nxt = res.get("nextCursor")
            if not isinstance(nxt, str) or not nxt or len(tools) >= MAX_TOOLS:
                break
            cursor = nxt
        return tools[:MAX_TOOLS]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.initialize()
        return render_content(self._rpc("tools/call", {"name": name, "arguments": arguments}))
