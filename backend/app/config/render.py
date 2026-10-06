"""`@hootpr configuration` output: effective YAML with provenance comments (phase-3 R20)."""

import json
from collections.abc import Mapping
from typing import Any

import yaml

from app.config.loader import ResolvedConfig

SOURCE_LABELS: dict[str, str] = {
    "yaml": ".hootpr.yaml",
    "repo": "repository settings",
    "org": "organization settings",
    "default": "defaults",
}
_WIDTH = 1_000_000


def _inline(value: Any) -> str:
    """A one-line YAML rendering of a scalar or a list of scalars."""
    text = yaml.safe_dump(value, default_flow_style=True, width=_WIDTH, allow_unicode=True)
    text = text.removesuffix("\n").removesuffix("\n...").rstrip("\n")
    if "\n" in text:
        # Multi-line strings: JSON is valid YAML and always fits on one line.
        return json.dumps(value, ensure_ascii=False)
    return text


def _block_items(items: list[Any], pad: str) -> list[str]:
    out: list[str] = []
    for item in items:
        dumped = yaml.safe_dump(
            item, default_flow_style=False, sort_keys=False, width=_WIDTH, allow_unicode=True
        ).rstrip("\n")
        for i, line in enumerate(dumped.split("\n")):
            out.append(f"{pad}{'- ' if i == 0 else '  '}{line}")
    return out


def _lines(data: Mapping[str, Any], prov: Mapping[str, str], prefix: str, indent: int) -> list[str]:
    out: list[str] = []
    pad = "  " * indent
    for key, value in data.items():
        path = f"{prefix}{key}"
        src = prov.get(path)
        note = f"  # from {SOURCE_LABELS[src]}" if src else ""
        if isinstance(value, Mapping) and value:
            out.append(f"{pad}{key}:")
            out += _lines(value, prov, f"{path}.", indent + 1)
        elif isinstance(value, list) and any(isinstance(v, Mapping | list) for v in value):
            out.append(f"{pad}{key}:{note}")
            out += _block_items(value, pad + "  ")
        else:
            out.append(f"{pad}{key}: {_inline(value)}{note}")
    return out


def render_configuration(resolved: ResolvedConfig) -> str:
    """Effective config as YAML; each leaf set by a source ends with ``# from <source>``."""
    head = f"# Effective HootPR configuration (source: {SOURCE_LABELS[resolved.source]})"
    body = _lines(resolved.config.model_dump(mode="json"), resolved.provenance, "", 0)
    return "\n".join([head, *body]) + "\n"
