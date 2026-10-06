import json
from typing import Any

from hootpr_evals.case import ExpectedIssue
from hootpr_evals.oracle_llm import OracleLLM, stage_of

ISSUE = ExpectedIssue(
    id="sqli",
    path="app/users.py",
    line_range=(9, 10),
    category="security",
    severity="critical",
    description="User-controlled name is interpolated into the SQL string (SQL injection).",
)


def chat(llm: OracleLLM, **body: Any) -> dict[str, Any]:
    client = llm.client()
    out: dict[str, Any] = client.chat.completions.create(model="m", **body).model_dump()
    return out


def rf(name: str) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": {}, "strict": True}}


def test_agent_reports_the_issues_of_its_task_files() -> None:
    llm = OracleLLM([ISSUE], noise=True)
    out = chat(
        llm,
        messages=[
            {"role": "system", "content": "[hootpr:agent]"},
            {"role": "user", "content": '<task ordinal="0">\n### FILE app/users.py'},
        ],
        tools=[{"type": "function", "function": {"name": "done", "parameters": {"type": "object"}}}],
    )
    calls = out["choices"][0]["message"]["tool_calls"]
    names = [c["function"]["name"] for c in calls]
    assert names == ["report_finding", "report_finding", "done"]
    first = json.loads(calls[0]["function"]["arguments"])
    assert (first["path"], first["start_line"], first["end_line"], first["category"]) == (
        "app/users.py",
        9,
        10,
        "security",
    )
    assert json.loads(calls[1]["function"]["arguments"])["confidence"] < 0.45  # noise the judge must filter
    assert out["usage"]["prompt_tokens"] > 0


def test_agent_ignores_issues_outside_its_files_and_finishes_after_tool_results() -> None:
    llm = OracleLLM([ISSUE])
    tools = [{"type": "function", "function": {"name": "done", "parameters": {"type": "object"}}}]
    other = chat(
        llm,
        messages=[{"role": "system", "content": "[hootpr:agent]"}, {"role": "user", "content": "### FILE b.py"}],
        tools=tools,
    )
    assert [c["function"]["name"] for c in other["choices"][0]["message"]["tool_calls"]] == ["done"]
    follow = chat(
        llm,
        messages=[
            {"role": "system", "content": "[hootpr:agent]"},
            {"role": "user", "content": "### FILE app/users.py"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "done", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ],
        tools=tools,
    )
    assert [c["function"]["name"] for c in follow["choices"][0]["message"]["tool_calls"]] == ["done"]


def test_structured_stages_and_matcher() -> None:
    llm = OracleLLM([ISSUE])
    tri = chat(llm, messages=[{"role": "user", "content": "### FILE app/users.py"}], response_format=rf("TriageResult"))
    assert json.loads(tri["choices"][0]["message"]["content"])["files"][0]["decision"] == "deep"
    plan = chat(
        llm,
        messages=[{"role": "user", "content": "### FILE app/users.py [deep]\n### FILE README.md [light]"}],
        response_format=rf("ReviewPlan"),
    )
    assert json.loads(plan["choices"][0]["message"]["content"])["tasks"][0]["files"] == ["app/users.py"]
    single = chat(
        llm, messages=[{"role": "user", "content": "### FILE app/users.py"}], response_format=rf("SinglePassFindings")
    )
    assert json.loads(single["choices"][0]["message"]["content"])["findings"][0]["severity"] == "critical"
    judge = chat(
        llm, messages=[{"role": "user", "content": "### FINDING 0\n### FINDING 1"}], response_format=rf("JudgeBatch")
    )
    assert [v["index"] for v in json.loads(judge["choices"][0]["message"]["content"])["verdicts"]] == [0, 1]
    summ = chat(
        llm, messages=[{"role": "user", "content": "### FILE app/users.py"}], response_format=rf("WalkthroughSummary")
    )
    assert json.loads(summ["choices"][0]["message"]["content"])["changes"][0]["files"] == ["app/users.py"]
    match = chat(
        llm, messages=[{"role": "user", "content": "### ISSUE\n### FINDING"}], response_format=rf("MatchVerdict")
    )
    assert json.loads(match["choices"][0]["message"]["content"])["same_issue"] is True
    assert llm.stages == [
        "TriageResult",
        "ReviewPlan",
        "SinglePassFindings",
        "JudgeBatch",
        "WalkthroughSummary",
        "MatchVerdict",
    ]


def test_stage_detection_falls_back_to_the_embedded_schema_title() -> None:
    body = {
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": 'Return JSON: {"title":"JudgeBatch","type":"object"}'}],
    }
    assert stage_of(body) == "JudgeBatch"
    assert stage_of({"messages": [], "tools": [{}]}) == "agent"
    assert stage_of({"messages": []}) is None


def test_oracle_applies_learning_effects() -> None:
    issues = [
        ExpectedIssue(id="s", path="a.py", line_range=(1, 1), category="style", severity="nitpick",
                      description="d", learning_effect="suppress"),
        ExpectedIssue(id="r", path="a.py", line_range=(2, 2), category="security", severity="major",
                      description="d", learning_effect="require"),
        ExpectedIssue(id="n", path="a.py", line_range=(3, 3), category="bug", severity="major", description="d"),
    ]  # fmt: skip
    oracle = OracleLLM(issues)
    plain = oracle.agent_titles("### FILE a.py")
    with_block = oracle.agent_titles("### FILE a.py\n<team_learnings>\n- [L1] x\n</team_learnings>")
    assert plain == {"s", "n"} and with_block == {"r", "n"}


def test_oracle_agent_and_single_pass_honour_the_learnings_block() -> None:
    issues = [
        ExpectedIssue(id="s", path="a.py", line_range=(1, 1), category="style", severity="nitpick",
                      description="suppressed", learning_effect="suppress"),
        ExpectedIssue(id="n", path="a.py", line_range=(3, 3), category="bug", severity="major", description="kept"),
    ]  # fmt: skip
    llm = OracleLLM(issues)
    user = "### FILE a.py\n<team_learnings>\n- [L1] x\n</team_learnings>"
    tools = [{"type": "function", "function": {"name": "done", "parameters": {"type": "object"}}}]
    out = chat(llm, messages=[{"role": "system", "content": "[hootpr:agent]"}, {"role": "user", "content": user}],
               tools=tools)  # fmt: skip
    reported = [
        json.loads(c["function"]["arguments"])["body"]
        for c in out["choices"][0]["message"]["tool_calls"]
        if c["function"]["name"] == "report_finding"
    ]
    assert reported == ["kept"]
    single = chat(llm, messages=[{"role": "user", "content": user}], response_format=rf("SinglePassFindings"))
    assert [f["body"] for f in json.loads(single["choices"][0]["message"]["content"])["findings"]] == ["kept"]


def test_oracle_answers_embeddings_with_the_hashing_embedder() -> None:
    from hootpr_evals.embed import hash_embed

    llm = OracleLLM([ISSUE])
    resp = llm.client().embeddings.create(model="e", input=["print statements in cli", "rows err"], dimensions=32)
    vectors = [d.embedding for d in resp.data]
    assert vectors == hash_embed(["print statements in cli", "rows err"], dims=32)
    assert [d.index for d in resp.data] == [0, 1] and resp.usage.total_tokens > 0
    assert llm.stages[-1] == "embeddings"
    default = llm.client().embeddings.create(model="e", input="single text")
    assert len(default.data[0].embedding) == 64


def test_oracle_answers_the_chat_agent_with_a_final_reply() -> None:
    llm = OracleLLM([ISSUE])
    out = chat(
        llm,
        messages=[{"role": "system", "content": "[hootpr:chat] You are HootPR."}, {"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
    )
    msg = out["choices"][0]["message"]
    assert not msg.get("tool_calls") and msg["content"]
    assert stage_of({"messages": [{"role": "system", "content": "[hootpr:chat] x"}], "tools": [{}]}) == "chat"
