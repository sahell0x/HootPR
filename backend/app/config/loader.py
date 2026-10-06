"""Config precedence: .hootpr.yaml (base branch) > repo UI > org UI > defaults (spec §9.1)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from app.config.schema import HootPRConfig
from app.config.validator import validate_yaml
from app.platforms.base import GitPlatform, RepoRef

SourceName = Literal["yaml", "repo", "org", "default"]
CONFIG_PATH = ".hootpr.yaml"


@dataclass(frozen=True)
class ResolvedConfig:
    config: HootPRConfig
    source: SourceName
    warnings: list[str] = field(default_factory=list)
    # Dotted leaf path -> the source that set it (phase-3 R20); defaults are absent.
    provenance: Mapping[str, SourceName] = field(default_factory=dict)


def leaf_paths(data: Mapping[str, Any], prefix: str = "") -> list[str]:
    """Dotted paths of every leaf; lists and empty mappings are leaves."""
    out: list[str] = []
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            out += leaf_paths(value, f"{path}.")
        else:
            out.append(path)
    return out


def _key(item: Any) -> str:
    return json.dumps(item, sort_keys=True, default=str)


def deep_merge(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Objects merge, lists union (dedupe, parent order first), scalars override. Pure."""
    out = dict(parent)
    for key, value in child.items():
        prev = out.get(key)
        if isinstance(prev, dict) and isinstance(value, dict):
            out[key] = deep_merge(prev, value)
        elif isinstance(prev, list) and isinstance(value, list):
            merged = list(prev)
            seen = {_key(x) for x in prev}
            for item in value:
                k = _key(item)
                if k not in seen:
                    seen.add(k)
                    merged.append(item)
            out[key] = merged
        else:
            out[key] = value
    return out


def resolve_config(
    yaml_data: dict[str, Any] | None,
    repo_settings: dict[str, Any] | None,
    org_settings: dict[str, Any] | None,
) -> ResolvedConfig:
    levels: tuple[tuple[SourceName, dict[str, Any] | None], ...] = (
        ("yaml", yaml_data),
        ("repo", repo_settings),
        ("org", org_settings),
    )
    sources = [(name, data) for name, data in levels if data]
    warnings: list[str] = []
    while sources:
        top_name, top = sources[0]
        data: dict[str, Any] = top
        provenance: dict[str, SourceName] = {p: top_name for p in leaf_paths(top)}
        if top.get("inheritance") is True:
            data = {}
            provenance = {}
            for name, d in reversed(sources):
                data = deep_merge(data, d)
                provenance.update({p: name for p in leaf_paths(d)})
        try:
            cfg = HootPRConfig.model_validate(data)
            return ResolvedConfig(cfg, top_name, warnings, provenance)
        except ValidationError as exc:
            warnings.append(
                f"{top_name} configuration is invalid and was ignored: {exc.error_count()} error(s)"
            )
            sources = sources[1:]
    return ResolvedConfig(HootPRConfig(), "default", warnings)


def load_effective_config(
    platform: GitPlatform,
    repo: RepoRef,
    base_ref: str,
    repo_settings: dict[str, Any] | None,
    org_settings: dict[str, Any] | None,
    *,
    head_sha: str | None = None,
) -> ResolvedConfig:
    """Effective config, reading `.hootpr.yaml` from the **base** ref.

    The head ref is never enforced, so a PR can't disable its own review (spec §9.1). With
    ``head_sha`` the PR's own file only adds notes to ``warnings`` (phase-3 R21).
    """
    text = platform.get_file(repo, CONFIG_PATH, base_ref)
    yaml_data: dict[str, Any] | None = None
    pre: list[str] = []
    if text is not None:
        v = validate_yaml(text)
        if v.valid:
            yaml_data = v.data
        else:
            first = v.errors[0]
            where = f" (line {first.line})" if first.line else ""
            pre.append(
                f"{CONFIG_PATH} is invalid{where}: {_error_text(first.path, first.message)}; "
                "falling back to dashboard settings"
            )
    if head_sha is not None:
        pre += _head_notes(platform.get_file(repo, CONFIG_PATH, head_sha), text)
    resolved = resolve_config(yaml_data, repo_settings, org_settings)
    return ResolvedConfig(
        resolved.config, resolved.source, pre + resolved.warnings, resolved.provenance
    )


_PATH_MAX, _MESSAGE_MAX = 120, 200


def _one_line(text: str, max_len: int) -> str:
    flat = " ".join(text.replace("`", "'").split())
    return flat if len(flat) <= max_len else flat[: max_len - 1] + "…"


def _error_text(path: str, message: str) -> str:
    """Validation error of a repo-controlled YAML file, safe to post: YAML keys can carry
    newlines, mentions, HTML or GitLab quick actions, so both parts are flattened to one line,
    capped, and the key path is quoted as code."""
    return f"`{_one_line(path, _PATH_MAX)}` {_one_line(message, _MESSAGE_MAX)}"


def _head_notes(head: str | None, base: str | None) -> list[str]:
    if head is None or head == base:
        return []
    v = validate_yaml(head)
    if not v.valid:
        first = v.errors[0]
        where = f" (line {first.line})" if first.line else ""
        return [
            f"{CONFIG_PATH} in this pull request is invalid{where}: "
            f"{_error_text(first.path, first.message)}; it will be ignored after merge."
        ]
    return [
        f"Changes to {CONFIG_PATH} in this pull request take effect after it is merged "
        "(HootPR reads the configuration from the base branch)."
    ]


def head_config_notes(
    platform: GitPlatform, repo: RepoRef, base_ref: str, head_sha: str
) -> list[str]:
    """Notes about the PR's own `.hootpr.yaml` (never enforced, phase-3 R21)."""
    return _head_notes(
        platform.get_file(repo, CONFIG_PATH, head_sha),
        platform.get_file(repo, CONFIG_PATH, base_ref),
    )
