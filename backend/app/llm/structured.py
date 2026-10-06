"""Structured-output helpers: strict JSON Schema, schema instruction, JSON extraction."""

import copy
import json
from typing import Any

from pydantic import BaseModel

# Keywords whose value maps *names* to sub-schemas (a field may be called "default").
_SCHEMA_MAPS = ("properties", "$defs", "definitions", "patternProperties")


def _strictify(node: Any) -> None:
    """OpenAI strict mode: every object closed, every property required, no defaults."""
    if isinstance(node, list):
        for item in node:
            _strictify(item)
        return
    if not isinstance(node, dict):
        return
    node.pop("default", None)
    props = node.get("properties")
    if isinstance(props, dict):
        node["additionalProperties"] = False
        node["required"] = list(props.keys())
    for key, value in node.items():
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            for sub in value.values():
                _strictify(sub)
        else:
            _strictify(value)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = copy.deepcopy(model.model_json_schema())
    _strictify(schema)
    return schema


def schema_instruction(model: type[BaseModel]) -> str:
    return (
        "Respond with only a JSON object (no prose, no code fences) "
        "that matches this JSON Schema:\n"
        + json.dumps(model.model_json_schema(), separators=(",", ":"))
    )


def extract_json_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None
