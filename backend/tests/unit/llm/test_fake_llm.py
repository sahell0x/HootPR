import openai
import pytest

from tests.fakes.fake_llm import FakeLLM


def test_fake_returns_queued_reply_with_usage() -> None:
    fake = FakeLLM()
    fake.reply('{"ok": true}', prompt_tokens=12, cached_tokens=4, completion_tokens=3)
    resp = fake.openai_client().chat.completions.create(
        model="m", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.choices[0].message.content == '{"ok": true}'
    assert resp.usage is not None and resp.usage.prompt_tokens == 12
    assert (
        resp.usage.prompt_tokens_details is not None
        and resp.usage.prompt_tokens_details.cached_tokens == 4
    )
    assert fake.requests[0]["body"]["model"] == "m"


def test_fake_rejects_unsupported_json_schema() -> None:
    fake = FakeLLM(json_schema=False)
    with pytest.raises(openai.BadRequestError):
        fake.openai_client().chat.completions.create(
            model="m",
            messages=[],
            response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        )


def test_fake_429_then_ok() -> None:
    fake = FakeLLM(fail_429=1)
    client = fake.openai_client()
    with pytest.raises(openai.RateLimitError):
        client.chat.completions.create(model="m", messages=[])
    client.chat.completions.create(model="m", messages=[])


def test_fake_embeddings() -> None:
    resp = FakeLLM(dims=4).openai_client().embeddings.create(model="e", input=["a", "b"])
    assert [len(d.embedding) for d in resp.data] == [4, 4]
