from decimal import Decimal

from pydantic import BaseModel

from app.llm.structured import extract_json_object, schema_instruction, strict_json_schema
from app.llm.types import RoleConfig, Usage, compute_cost, excerpt, role_configs
from app.settings import Settings


class Inner(BaseModel):
    x: int = 1


class Outer(BaseModel):
    name: str
    tags: list[str] = []
    inner: Inner | None = None


def test_strict_schema() -> None:
    s = strict_json_schema(Outer)
    assert s["additionalProperties"] is False
    assert sorted(s["required"]) == ["inner", "name", "tags"]
    inner = s["$defs"]["Inner"]
    assert inner["additionalProperties"] is False and inner["required"] == ["x"]
    assert "default" not in str(s)


def test_schema_instruction_mentions_schema() -> None:
    text = schema_instruction(Outer)
    assert "JSON Schema" in text and '"name"' in text


def test_extract_json_object() -> None:
    assert extract_json_object('Sure!\n```json\n{"a": {"b": "}"}}\n```') == '{"a": {"b": "}"}}'
    assert extract_json_object("no json here") is None
    assert extract_json_object('{"a": "\\"{"}') == '{"a": "\\"{"}'
    assert extract_json_object('{ unbalanced then {"ok": 1}') == '{"ok": 1}'


def test_compute_cost_and_excerpt() -> None:
    cfg = RoleConfig(
        "cheap",
        "https://api.openai.com/v1",
        "k",
        "m",
        Decimal("0.10"),
        Decimal("0.01"),
        Decimal("0.50"),
    )
    assert compute_cost(cfg, Usage(1_000_000, 200_000, 100_000)) == Decimal("0.132")
    assert compute_cost(RoleConfig("cheap", "u", "k", "m"), Usage(10, 0, 5)) is None
    assert cfg.provider_host == "api.openai.com"
    assert len(excerpt("x" * 20000, full=False).encode()) <= 8192
    assert len(excerpt("x" * 20000, full=True)) == 20000


def test_role_configs_from_settings(settings: Settings) -> None:
    roles = role_configs(settings)
    assert set(roles) == {"review", "cheap", "embed"}
    assert roles["cheap"].model == settings.llm_cheap_model
    assert roles["embed"].dimensions == settings.llm_embed_dimensions
    assert "api_key" not in repr(roles["review"])


def test_excerpt_does_not_split_multibyte() -> None:
    out = excerpt("é" * 10000, full=False)
    assert len(out.encode()) <= 8192 and set(out) == {"é"}


class Tricky(BaseModel):
    default: str = "x"
    properties: int = 0


def test_strict_schema_keeps_fields_named_like_keywords() -> None:
    s = strict_json_schema(Tricky)
    assert set(s["properties"]) == {"default", "properties"}
    assert sorted(s["required"]) == ["default", "properties"]
    assert "default" not in s["properties"]["default"]
