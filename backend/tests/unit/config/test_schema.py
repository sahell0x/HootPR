import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config.schema import HootPRConfig, config_json_schema

RULE = {
    "id": "no-print",
    "language": "python",
    "message": "Use logging.",
    "rule": {"pattern": "print($$$A)"},
}


def test_ast_grep_instructions_and_tool() -> None:
    cfg = HootPRConfig.model_validate(
        {
            "reviews": {
                "ast_grep_instructions": [RULE],
                "tools": {
                    "ast_grep": {
                        "essential_rules": True,
                        "rule_dirs": ["rules"],
                        "util_dirs": ["utils"],
                    }
                },
            }
        }
    )
    r = cfg.reviews.ast_grep_instructions[0]
    assert (r.id, r.language, r.severity, r.files) == ("no-print", "python", "warning", [])
    assert r.rule == {"pattern": "print($$$A)"}
    t = cfg.reviews.tools.ast_grep
    assert t.enabled and t.essential_rules and t.rule_dirs == ["rules"] and t.util_dirs == ["utils"]


def test_ast_grep_defaults() -> None:
    t = HootPRConfig().reviews.tools.ast_grep
    assert (t.enabled, t.essential_rules, t.rule_dirs, t.util_dirs) == (True, False, [], [])


@pytest.mark.parametrize(
    "bad",
    [
        {**RULE, "id": "bad id!"},
        {**RULE, "rule": {}},
        {**RULE, "severity": "fatal"},
        {**RULE, "language": ""},
        {**RULE, "extra": 1},
    ],
)
def test_ast_grep_rule_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        HootPRConfig.model_validate({"reviews": {"ast_grep_instructions": [bad]}})


def test_ast_grep_rule_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate ast_grep_instructions id"):
        HootPRConfig.model_validate({"reviews": {"ast_grep_instructions": [RULE, RULE]}})


def test_path_instruction_path_required() -> None:
    with pytest.raises(ValidationError):
        HootPRConfig.model_validate(
            {"reviews": {"path_instructions": [{"path": "", "instructions": "x"}]}}
        )


def _walk(schema: dict[str, Any], node: dict[str, Any], where: str, out: list[str]) -> None:
    if "$ref" in node:
        node = schema["$defs"][node["$ref"].split("/")[-1]]
    for name, prop in (node.get("properties") or {}).items():
        if not prop.get("description"):
            out.append(f"{where}.{name}")
        for sub in [prop, *(prop.get("anyOf") or []), prop.get("items") or {}]:
            if "$ref" in sub or "properties" in sub:
                _walk(schema, sub, f"{where}.{name}", out)


def test_every_schema_property_has_a_description() -> None:
    schema = config_json_schema("https://hootpr.example")
    missing: list[str] = []
    _walk(schema, schema, "", missing)
    assert missing == []


def test_list_of_object_fields_reference_defs() -> None:
    schema = config_json_schema("https://hootpr.example")
    reviews = schema["$defs"]["Reviews"]["properties"]
    for name in ("path_instructions", "ast_grep_instructions"):
        assert reviews[name]["type"] == "array"
        assert "$ref" in reviews[name]["items"]
    rule = schema["$defs"]["AstGrepRule"]["properties"]["rule"]
    assert rule["type"] == "object" and rule["additionalProperties"] is True


def test_schema_id_uses_base_url() -> None:
    s = config_json_schema("https://hootpr.example/")
    assert s["$id"] == "https://hootpr.example/schema/hootpr.v1.json"
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_exported_schema_file_is_current() -> None:
    path = Path(__file__).resolve().parents[3] / "hootpr.v1.schema.json"
    expected = (
        json.dumps(config_json_schema("http://localhost:3000"), indent=2, sort_keys=True) + "\n"
    )
    assert path.exists() and path.read_text() == expected, (
        "run: uv run python -m app.scripts.export_config_schema hootpr.v1.schema.json"
    )
