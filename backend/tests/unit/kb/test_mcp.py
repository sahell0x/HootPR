"""MCP client + external tools + the review/chat agents calling an MCP tool (phase 7)."""

import json
from typing import Any

import httpx
import pytest

from app.config.schema import HootPRConfig
from app.kb.external import ExternalTools, McpServerConfig, exposed_name
from app.kb.mcp_client import McpClient, McpError, McpPolicy, _sse_messages
from app.kb.resolve import discovered_payload
from app.llm.types import TraceContext
from app.review.agent import AgentLimits, Toolbox, run_agent
from app.review.graph import CodeGraph
from app.review.schemas import PlanTask
from app.review.tool_results import ToolResults
from tests.fakes.engine_llm import EngineFakeLLM, done_call, make_test_gateway, tool_call
from tests.fakes.fake_mcp import FakeMcpServer

URL = "https://mcp.example.com/mcp"
PUBLIC = lambda host, port: ["93.184.216.34"]  # noqa: E731
POLICY = McpPolicy(resolver=PUBLIC)
AUTH = {"Authorization": "Bearer secret-token"}
TASK = PlanTask(
    title="Users", files=["a.py"], focus=["api-contract"], rationale="r", related_symbols=[]
)
LIM = AgentLimits(max_steps=8, max_input_tokens=60_000)


def client(server: FakeMcpServer, headers: dict[str, str] | None = None) -> McpClient:
    http = httpx.Client(transport=server.transport())
    return McpClient(URL, AUTH if headers is None else headers, POLICY, http=http)


def discovered(server: FakeMcpServer) -> tuple[dict[str, Any], ...]:
    with client(server) as c:
        return tuple(discovered_payload(c.list_tools()))


def external(server: FakeMcpServer, allowed: tuple[str, ...] = ("lookup_doc",)) -> ExternalTools:
    cfg = McpServerConfig("docs", URL, AUTH, allowed, discovered(server))
    return ExternalTools.build(
        [cfg], http=httpx.Client(transport=server.transport()), resolver=PUBLIC
    )


@pytest.mark.parametrize("sse", [True, False])
def test_client_handshake_list_and_call(sse: bool) -> None:
    server = FakeMcpServer(sse=sse)
    with client(server) as c:
        tools = c.list_tools()
        assert [t.name for t in tools] == ["lookup_doc", "delete_everything"]
        assert c.call_tool("lookup_doc", {"topic": "users"}).startswith("Docs for users")
        assert c.call_tool("delete_everything", {}) == "error: boom"
    methods = [r.get("method") for r in server.requests]
    assert methods == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
        "tools/call",
    ]
    assert all(h.get("mcp-session-id") == "sess-123" for h in server.headers[1:])


def test_client_rejects_bad_credentials_and_rpc_errors() -> None:
    server = FakeMcpServer()
    with pytest.raises(McpError, match="rejected the credentials"), client(server, {}) as c:
        c.list_tools()


def test_client_never_contacts_private_hosts() -> None:
    server = FakeMcpServer()
    http = httpx.Client(transport=server.transport())
    for url, resolver in [
        ("https://127.0.0.1/mcp", PUBLIC),
        ("https://mcp.example.com/mcp", lambda h, p: ["10.0.0.5"]),
        ("http://mcp.example.com/mcp", PUBLIC),
        ("https://169.254.169.254/latest", PUBLIC),
    ]:
        c = McpClient(url, AUTH, McpPolicy(resolver=resolver), http=http)
        with pytest.raises(McpError, match="blocked URL"):
            c.list_tools()
    assert server.requests == []


def test_sse_parser_handles_multiple_events() -> None:
    text = 'data: {"jsonrpc":"2.0","method":"x"}\n\nevent: message\ndata: {"id":1}\n\n'
    assert _sse_messages(text) == [{"jsonrpc": "2.0", "method": "x"}, {"id": 1}]


def test_external_tools_expose_only_allowlisted_tools() -> None:
    tools = external(FakeMcpServer())
    names = [s["function"]["name"] for s in tools.specs()]
    assert names == ["mcp__docs__lookup_doc"]
    assert tools.handles("mcp__docs__lookup_doc")
    assert not tools.handles(exposed_name("docs", "delete_everything"))
    assert tools.call("mcp__docs__delete_everything", {}).startswith("error: unknown tool")
    out = tools.call("mcp__docs__lookup_doc", {"topic": "billing"})
    assert out.startswith('<untrusted source="mcp:docs/lookup_doc">')
    assert "Docs for billing" in out
    empty = ExternalTools.build([McpServerConfig("docs", URL, AUTH, (), ())])
    assert not empty and empty.specs() == []


def test_external_tools_enforce_call_budget_and_output_cap() -> None:
    server = FakeMcpServer()
    cfg = McpServerConfig("docs", URL, AUTH, ("lookup_doc",), discovered(server))
    tools = ExternalTools.build(
        [cfg],
        http=httpx.Client(transport=server.transport()),
        resolver=PUBLIC,
        max_calls=1,
    )
    assert "Docs for" in tools.call("mcp__docs__lookup_doc", {"topic": "a"})
    assert "budget" in tools.call("mcp__docs__lookup_doc", {"topic": "b"})


def test_review_agent_calls_allowed_mcp_tool() -> None:
    """Done-when: an MCP tool on a (fake) MCP server is callable by the review agent."""
    server = FakeMcpServer()
    tools = external(server)
    fake = EngineFakeLLM()
    fake.agent_turns = [
        [tool_call("mcp__docs__lookup_doc", {"topic": "get_user"})],
        [done_call("consulted docs")],
    ]
    gw, _ = make_test_gateway(fake)
    rows: list[tuple[Any, ...]] = []
    out = run_agent(
        gw,
        TASK,
        0,
        "pack",
        Toolbox(None, CodeGraph.empty(), ToolResults(), LIM, external=tools),
        LIM,
        HootPRConfig(),
        trace=TraceContext(),
        on_step=lambda *a: rows.append(a),
    )
    assert out.stop_reason == "done" and out.steps == 1
    calls = [r for r in server.requests if r.get("method") == "tools/call"]
    assert calls == [
        {
            "jsonrpc": "2.0",
            "id": calls[0]["id"],
            "method": "tools/call",
            "params": {"name": "lookup_doc", "arguments": {"topic": "get_user"}},
        }
    ]
    agent_reqs = [r["body"] for r in fake.requests if r["body"].get("tools")]
    offered = {t["function"]["name"] for t in agent_reqs[0]["tools"]}
    assert "mcp__docs__lookup_doc" in offered and "mcp__docs__delete_everything" not in offered
    tool_msgs = [m for m in agent_reqs[1]["messages"] if m["role"] == "tool"]
    assert "get_user now requires org_id" in tool_msgs[0]["content"]
    results = [r for r in rows if r[0] == "tool_result" and r[1] == "mcp__docs__lookup_doc"]
    assert results and "Docs for get_user" in results[0][3]


def test_chat_agent_offers_mcp_tools(settings: Any) -> None:
    from app.chat.agent import ChatContext, run_chat_agent

    server = FakeMcpServer()
    tools = external(server)
    fake = EngineFakeLLM()
    fake.chat_turns = [
        [tool_call("mcp__docs__lookup_doc", {"topic": "x"})],
    ]
    gw, _ = make_test_gateway(fake)
    ctx = ChatContext("dev", "what changed?", "o/r#1", "t", "", (), None, None, None, None, "", ())
    toolbox = Toolbox(None, CodeGraph.empty(), ToolResults(), LIM, external=tools)
    run_chat_agent(
        gw, ctx, HootPRConfig(), settings, toolbox=toolbox, allow_shell=False,
        add_learning=None, trace=TraceContext(),
    )  # fmt: skip
    first = next(r["body"] for r in fake.requests if r["body"].get("tools"))
    assert "mcp__docs__lookup_doc" in {t["function"]["name"] for t in first["tools"]}
    json.dumps(first)  # serialisable
