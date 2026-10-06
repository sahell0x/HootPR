import json
from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.llm.gateway import LLMGateway
from app.llm.metering import InMemoryRecorder
from app.llm.types import (
    ProviderUnavailable,
    RoleConfig,
    StructuredOutputError,
    ToolsUnsupported,
    TraceContext,
)
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.kv import DictKV

TRACE = TraceContext()
MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]


class Verdict(BaseModel):
    verdict: str
    score: int


def gateway(
    fake: FakeLLM, kv: DictKV | None = None, **kw: object
) -> tuple[LLMGateway, InMemoryRecorder, list[float]]:
    rec, sleeps = InMemoryRecorder(), []
    roles = {
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
    }  # type: ignore[misc]
    gw = LLMGateway(
        roles,
        rec,
        kv or DictKV(),
        client_factory=lambda cfg: fake.openai_client(),
        sleep=sleeps.append,
        **kw,
    )  # type: ignore[arg-type]
    return gw, rec, sleeps


def test_json_schema_first_rung() -> None:
    fake = FakeLLM()
    fake.reply(
        '{"verdict": "keep", "score": 3}', prompt_tokens=10, cached_tokens=2, completion_tokens=5
    )
    gw, rec, _ = gateway(fake)
    res = gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=100, trace=TRACE)
    assert isinstance(res.parsed, Verdict) and res.parsed.score == 3
    assert res.structured_mode == "json_schema"
    rf = fake.requests[0]["body"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert fake.requests[0]["body"]["max_completion_tokens"] == 100
    [r] = rec.records
    assert (r.usage.input_tokens, r.usage.cached_tokens, r.usage.output_tokens) == (10, 2, 5)
    assert (
        r.cost_usd == Decimal("0.00000332")
        and r.status == "ok"
        and r.structured_mode == "json_schema"
    )


def test_falls_back_to_json_object_and_caches_capability() -> None:
    fake = FakeLLM(json_schema=False)
    fake.reply('{"verdict": "drop", "score": 1}')
    fake.reply('{"verdict": "keep", "score": 2}')
    kv = DictKV()
    gw, rec, _ = gateway(fake, kv)
    res = gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=50, trace=TRACE)
    assert res.structured_mode == "json_object"
    assert [r.status for r in rec.records] == ["error", "ok"]
    sys_msgs = [m["content"] for m in fake.requests[1]["body"]["messages"] if m["role"] == "system"]
    assert any("JSON Schema" in m for m in sys_msgs)
    gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=50, trace=TRACE)
    assert (
        fake.requests[2]["body"]["response_format"]["type"] == "json_object"
    )  # skipped failed rung
    assert any(k.startswith("llm:cap:mode:") for k in kv.data) and 86400 in kv.ttls.values()


def test_falls_back_to_text_and_extracts_json() -> None:
    fake = FakeLLM(json_schema=False, json_object=False)
    fake.reply('Sure! ```json\n{"verdict": "keep", "score": 9}\n```')
    gw, _, _ = gateway(fake)
    res = gw.complete("cheap", MSGS, response_model=Verdict, max_output_tokens=50, trace=TRACE)
    assert res.structured_mode == "text" and res.parsed == Verdict(verdict="keep", score=9)
    assert "response_format" not in fake.requests[-1]["body"]


def test_invalid_json_retried_once_with_error() -> None:
    fake = FakeLLM()
    fake.reply('{"verdict": "keep"}')
    fake.reply('{"verdict": "keep", "score": 4}')
    gw, _, _ = gateway(fake)
    res = gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=50, trace=TRACE)
    assert res.parsed == Verdict(verdict="keep", score=4)
    last = fake.requests[-1]["body"]["messages"][-1]["content"]
    assert "score" in last and "invalid" in last.lower()


def test_result_usage_and_cost_cover_the_validation_retry() -> None:
    """Callers sum LLMResult.usage/cost into reviews; the retry call must be counted too."""
    fake = FakeLLM()
    fake.reply('{"verdict": "keep"}', prompt_tokens=10, cached_tokens=2, completion_tokens=5)
    fake.reply(
        '{"verdict": "keep", "score": 4}', prompt_tokens=20, cached_tokens=0, completion_tokens=7
    )
    gw, rec, _ = gateway(fake)
    res = gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=50, trace=TRACE)
    assert (res.usage.input_tokens, res.usage.cached_tokens, res.usage.output_tokens) == (
        30,
        2,
        12,
    )
    ok = [r for r in rec.records if r.status == "ok"]
    assert len(ok) == 2
    assert res.cost_usd == sum((r.cost_usd or Decimal(0) for r in ok), Decimal(0))


def test_invalid_twice_raises() -> None:
    fake = FakeLLM()
    fake.reply("not json")
    fake.reply('{"nope": 1}')
    gw, _, _ = gateway(fake)
    with pytest.raises(StructuredOutputError):
        gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=50, trace=TRACE)


def test_tools_unsupported_is_detected_and_cached() -> None:
    fake = FakeLLM(tools=False)
    gw, _, _ = gateway(fake)
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    ]
    with pytest.raises(ToolsUnsupported):
        gw.complete("review", MSGS, tools=tools, max_output_tokens=50, trace=TRACE)
    n = len(fake.requests)
    with pytest.raises(ToolsUnsupported):
        gw.complete("review", MSGS, tools=tools, max_output_tokens=50, trace=TRACE)
    assert len(fake.requests) == n


def test_tool_calls_are_returned() -> None:
    fake = FakeLLM()
    fake.reply(
        None,
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": "a"})},
            }
        ],
    )
    gw, _, _ = gateway(fake)
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    ]
    res = gw.complete("review", MSGS, tools=tools, max_output_tokens=50, trace=TRACE)
    assert res.tool_calls[0].name == "read_file" and json.loads(res.tool_calls[0].arguments) == {
        "path": "a"
    }


def test_retries_429_with_backoff_then_succeeds() -> None:
    fake = FakeLLM(fail_429=2)
    fake.reply('{"verdict": "k", "score": 1}')
    gw, rec, sleeps = gateway(fake)
    gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=10, trace=TRACE)
    assert sleeps == [0.0, 0.0]  # Retry-After: 0 honored
    assert [r.status for r in rec.records] == ["ok"]


def test_provider_unavailable_after_three_attempts() -> None:
    fake = FakeLLM(fail_500=5)
    gw, rec, sleeps = gateway(fake)
    with pytest.raises(ProviderUnavailable):
        gw.complete("review", MSGS, max_output_tokens=10, trace=TRACE)
    assert len(sleeps) == 2 and len(fake.requests) == 3
    assert [r.status for r in rec.records] == ["error"]


def test_max_tokens_fallback() -> None:
    fake = FakeLLM(max_completion_tokens=False)
    gw, _, _ = gateway(fake)
    gw.complete("cheap", MSGS, max_output_tokens=10, trace=TRACE)
    assert fake.requests[-1]["body"]["max_tokens"] == 10
    gw.complete("cheap", MSGS, max_output_tokens=10, trace=TRACE)
    assert "max_completion_tokens" not in fake.requests[-1]["body"]


def test_excerpts_are_capped() -> None:
    fake = FakeLLM()
    gw, rec, _ = gateway(fake)
    gw.complete(
        "cheap", [{"role": "user", "content": "x" * 50_000}], max_output_tokens=10, trace=TRACE
    )
    assert len(rec.records[0].request_excerpt.encode()) <= 8192


def test_embed() -> None:
    fake = FakeLLM(dims=4)
    gw, rec, _ = gateway(fake)
    vecs = gw.embed(["a", "b", "c"], TRACE)
    assert len(vecs) == 3 and len(vecs[0]) == 4
    assert rec.records[0].role == "embed" and rec.records[0].usage.input_tokens == 9


def test_non_retryable_errors_become_llm_error() -> None:
    import httpx

    from app.llm.types import LLMError

    fake = FakeLLM()
    original = fake.handler

    def unauthorized(request: httpx.Request) -> httpx.Response:
        original(request)
        return httpx.Response(401, json={"error": {"message": "bad key", "type": "auth"}})

    fake.handler = unauthorized  # type: ignore[method-assign]
    gw, rec, sleeps = gateway(fake)
    with pytest.raises(LLMError):
        gw.complete("cheap", MSGS, max_output_tokens=10, trace=TRACE)
    assert sleeps == [] and [r.status for r in rec.records] == ["error"]


def test_tools_400_unrelated_to_tools_is_not_cached_as_notools() -> None:
    fake = FakeLLM(json_schema=False)
    fake.reply('{"verdict": "k", "score": 1}')
    kv = DictKV()
    gw, _, _ = gateway(fake, kv)
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    res = gw.complete(
        "review", MSGS, tools=tools, response_model=Verdict, max_output_tokens=10, trace=TRACE
    )
    assert res.structured_mode == "json_object"
    assert not any(k.startswith("llm:cap:notools:") for k in kv.data)


def test_exponential_backoff_without_retry_after() -> None:
    import random

    fake = FakeLLM(fail_500=2)
    fake.reply('{"verdict": "k", "score": 1}')
    gw, _, sleeps = gateway(fake, rng=random.Random(0))
    gw.complete("review", MSGS, response_model=Verdict, max_output_tokens=10, trace=TRACE)
    assert 0.5 <= sleeps[0] <= 0.75 and 1.0 <= sleeps[1] <= 1.25


def test_tools_retry_with_reasoning_effort_none_and_cache_it() -> None:
    fake = FakeLLM(tools_need_no_effort=True)
    kv = DictKV()
    gw, _, _ = gateway(fake, kv)
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    ]
    gw.complete("review", MSGS, tools=tools, max_output_tokens=50, trace=TRACE)
    assert fake.requests[-1]["body"]["reasoning_effort"] == "none"
    n = len(fake.requests)
    gw.complete("review", MSGS, tools=tools, max_output_tokens=50, trace=TRACE)
    assert len(fake.requests) == n + 1  # cached: no rejected first attempt
    gw.complete("review", MSGS, max_output_tokens=50, trace=TRACE)
    assert "reasoning_effort" not in fake.requests[-1]["body"]  # only tool calls lose reasoning
