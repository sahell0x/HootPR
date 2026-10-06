from app.llm.types import TraceContext
from app.review.llm import MeteredLLM
from app.review.schemas import ReviewPlan, TriageResult
from tests.fakes.engine_llm import EngineFakeLLM, make_test_gateway, report_call

T = TraceContext()


def test_fake_routes_structured_stages_by_schema_name() -> None:
    fake = EngineFakeLLM()
    gw, _ = make_test_gateway(fake)
    tri = gw.complete(
        "cheap",
        [{"role": "user", "content": "### FILE a.py\n### FILE b.md"}],
        response_model=TriageResult,
        max_output_tokens=100,
        trace=T,
    )
    assert [f.path for f in tri.parsed.files] == ["a.py", "b.md"]  # type: ignore[union-attr]
    plan = gw.complete(
        "review",
        [{"role": "user", "content": "### FILE a.py [deep]\n### FILE b.md [light]"}],
        response_model=ReviewPlan,
        max_output_tokens=100,
        trace=T,
    )
    assert plan.parsed.tasks[0].files == ["a.py"]  # type: ignore[union-attr]
    assert fake.stages == ["TriageResult", "ReviewPlan"]


def test_fake_detects_stage_from_embedded_schema_when_json_schema_unsupported() -> None:
    fake = EngineFakeLLM(json_schema=False)
    gw, _ = make_test_gateway(fake)
    tri = gw.complete(
        "cheap",
        [{"role": "user", "content": "### FILE a.py"}],
        response_model=TriageResult,
        max_output_tokens=100,
        trace=T,
    )
    assert [f.path for f in tri.parsed.files] == ["a.py"]  # type: ignore[union-attr]
    assert fake.stages[-1] == "TriageResult"


def test_fake_agent_reports_configured_findings_then_done() -> None:
    fake = EngineFakeLLM()
    fake.findings = [{"path": "a.py", "end_line": 2}]
    gw, _ = make_test_gateway(fake)
    res = gw.complete(
        "review",
        [{"role": "system", "content": "[hootpr:agent]"}, {"role": "user", "content": "go"}],
        tools=[
            {"type": "function", "function": {"name": "done", "parameters": {"type": "object"}}}
        ],
        max_output_tokens=100,
        trace=T,
    )
    assert [c.name for c in res.tool_calls] == ["report_finding", "done"]
    assert report_call(0, path="x.py")["function"]["name"] == "report_finding"


def test_metered_llm_sums_usage_cost_and_models() -> None:
    fake = EngineFakeLLM()
    gw, _ = make_test_gateway(fake)
    llm = MeteredLLM(gw)
    assert llm.cost_usd is None
    for role in ("cheap", "review", "review"):
        llm.complete(
            role,  # type: ignore[arg-type]
            [{"role": "user", "content": "### FILE a.py"}],
            response_model=TriageResult,
            max_output_tokens=100,
            trace=T,
        )
    assert llm.usage.input_tokens == 300 and llm.usage.output_tokens == 60
    assert llm.models == ["model-cheap", "model-review"]
    assert llm.cost_usd is not None and llm.cost_usd > 0


def test_metered_llm_counts_embeddings() -> None:
    fake = EngineFakeLLM()
    gw, rec = make_test_gateway(fake)
    llm = MeteredLLM(gw)
    vecs = llm.embed(["a b c", "d e f"], T)
    assert len(vecs) == 2
    embed_tokens = rec.records[-1].usage.input_tokens
    assert embed_tokens > 0 and llm.usage.input_tokens == embed_tokens
    assert llm.models == ["model-embed"] and llm.cost_usd is not None and llm.cost_usd > 0
