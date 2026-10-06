import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.llm.gateway import LLMGateway
from app.llm.metering import SqlCallRecorder
from app.llm.smoke import main, run_smoke
from app.llm.types import RoleConfig
from app.models import LlmCall
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.kv import DictKV

pytestmark = pytest.mark.integration


def make(fake: FakeLLM, sf: sessionmaker[Session]) -> LLMGateway:
    roles = {
        r: RoleConfig(
            r,
            "http://fake-llm/v1",
            "k",
            "gpt-5-nano",
            Decimal("0.05"),
            Decimal("0.005"),
            Decimal("0.40"),
            dimensions=8 if r == "embed" else None,
        )
        for r in ("review", "cheap", "embed")
    }
    return LLMGateway(
        roles, SqlCallRecorder(sf), DictKV(), client_factory=lambda c: fake.openai_client()
    )  # type: ignore[arg-type]


def test_smoke_meters_a_call(session_factory: sessionmaker[Session], db: Session) -> None:
    fake = FakeLLM()
    fake.reply('{"ok": true, "message": "hello"}', prompt_tokens=40, completion_tokens=8)
    out = run_smoke(make(fake, session_factory), "cheap")
    assert (
        out["reply"] == {"ok": True, "message": "hello"} and out["structured_mode"] == "json_schema"
    )
    row = db.execute(select(LlmCall)).scalar_one()
    assert (row.role, row.model, row.input_tokens, row.output_tokens, row.status) == (
        "cheap",
        "gpt-5-nano",
        40,
        8,
        "ok",
    )
    assert row.cost_usd == Decimal("0.000005")  # 0.0000052 rounded by NUMERIC(12,6)


def test_main_prints_json_and_handles_errors(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeLLM()
    fake.reply('{"ok": true, "message": "hi"}')
    assert main(["--role", "cheap"], gateway=make(fake, session_factory)) == 0
    assert json.loads(capsys.readouterr().out)["model"] == "gpt-5-nano"
    broken = FakeLLM(fail_500=5)
    assert main(["--role", "cheap"], gateway=make(broken, session_factory)) == 1
    assert "error" in json.loads(capsys.readouterr().out)


def test_embed_smoke(session_factory: sessionmaker[Session]) -> None:
    assert run_smoke(make(FakeLLM(dims=8), session_factory), "embed")["dimensions"] == 8
