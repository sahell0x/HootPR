"""YAML/settings validation with line numbers (spec §9.3)."""

from __future__ import annotations

import difflib
import types
import typing
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from app.config.schema import HootPRConfig

MAX_YAML_BYTES = 64 * 1024


@dataclass(frozen=True)
class ConfigIssue:
    line: int | None
    path: str
    message: str


@dataclass(frozen=True)
class YamlValidation:
    valid: bool
    errors: list[ConfigIssue]
    data: dict[str, Any] | None
    config: HootPRConfig | None


def _line_for(root: yaml.Node, loc: tuple[int | str, ...]) -> int:
    """1-based line of the YAML node at ``loc`` (or of the closest existing ancestor/key)."""
    node: yaml.Node = root
    line = node.start_mark.line + 1
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            pair = next(
                ((k, v) for k, v in node.value if getattr(k, "value", None) == str(part)), None
            )
            if pair is None:
                return line
            key, value = pair
            node = value
            # A scalar points at its value; a nested block at its key (the block starts below).
            anchor = value if isinstance(value, yaml.ScalarNode) else key
            line = anchor.start_mark.line + 1
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            if part >= len(node.value):
                return line
            node = node.value[part]
            line = node.start_mark.line + 1
        else:
            break
    return line


def _model_at(loc: tuple[int | str, ...]) -> type[BaseModel] | None:
    """The Pydantic model owning the last key of ``loc`` (list indexes are skipped)."""
    model: type[BaseModel] = HootPRConfig
    for part in loc:
        if isinstance(part, int):
            continue
        info = model.model_fields.get(str(part))
        if info is None:
            return None
        ann: Any = info.annotation
        while typing.get_origin(ann) in (list, typing.Union, types.UnionType):
            args = [a for a in typing.get_args(ann) if a is not type(None)]
            ann = args[0] if args else None
        if not (isinstance(ann, type) and issubclass(ann, BaseModel)):
            return None
        model = ann
    return model


def _message(err: Any) -> str:
    """Pydantic's message, or ``unknown key 'x' (did you mean 'y'?)`` (phase-3 R22)."""
    if err["type"] != "extra_forbidden":
        return str(err["msg"])
    loc = tuple(err["loc"])
    key = str(loc[-1])
    model = _model_at(loc[:-1])
    known = list(model.model_fields) if model else []
    close = difflib.get_close_matches(key, known, n=1, cutoff=0.6)
    return f"unknown key '{key}'" + (f" (did you mean '{close[0]}'?)" if close else "")


def _issues(exc: ValidationError, root: yaml.Node | None) -> list[ConfigIssue]:
    out: list[ConfigIssue] = []
    for err in exc.errors():
        loc = tuple(err["loc"])
        out.append(
            ConfigIssue(
                _line_for(root, loc) if root is not None else None,
                ".".join(str(p) for p in loc),
                _message(err),
            )
        )
    return out


def validate_yaml(text: str) -> YamlValidation:
    if len(text.encode()) > MAX_YAML_BYTES:
        return YamlValidation(
            False, [ConfigIssue(None, "", "file is larger than 64 KB")], None, None
        )
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        return YamlValidation(
            False, [ConfigIssue(line, "", f"YAML syntax error: {exc}")], None, None
        )
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return YamlValidation(
            False, [ConfigIssue(1, "", "top level must be a mapping")], None, None
        )
    try:
        cfg = HootPRConfig.model_validate(data)
    except ValidationError as exc:
        return YamlValidation(False, _issues(exc, root), data, None)
    return YamlValidation(True, [], data, cfg)


def validate_settings(data: dict[str, Any]) -> list[ConfigIssue]:
    try:
        HootPRConfig.model_validate(data)
    except ValidationError as exc:
        return _issues(exc, None)
    return []
