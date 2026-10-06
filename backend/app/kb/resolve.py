"""DB-facing helpers the review pipeline and the chat run use to set up phase-7 context."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.schema import HootPRConfig
from app.crypto import Crypto, DecryptionError
from app.kb.external import ExternalTools, McpServerConfig
from app.kb.linked import LinkedRepoSpec, dir_names
from app.kb.web_search import WebSearch, search_config
from app.logging import get_logger
from app.models import McpServer, Repository
from app.platforms.factory import repo_ref
from app.settings import Settings

log = get_logger(__name__)


def decode_headers(crypto: Crypto, enc: str | None) -> dict[str, str]:
    if not enc:
        return {}
    raw = json.loads(crypto.decrypt(enc))
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def encode_headers(crypto: Crypto, headers: dict[str, str]) -> str | None:
    return crypto.encrypt(json.dumps(headers)) if headers else None


def linked_repo_specs(
    s: Session, cfg: HootPRConfig, org_id: UUID, repo_id: UUID, settings: Settings
) -> tuple[tuple[LinkedRepoSpec, ...], list[str]]:
    """Linked repositories from the config that HootPR knows in the same org (+ ignored names)."""
    wanted: dict[str, str] = {}
    for lr in cfg.knowledge_base.linked_repositories:
        wanted.setdefault(lr.repository.strip().lower(), lr.instructions)
    if not wanted:
        return (), []
    rows = (
        s.execute(
            select(Repository).where(
                Repository.org_id == org_id,
                Repository.id != repo_id,
                Repository.installation_id.is_not(None),
                func.lower(Repository.full_name).in_(list(wanted)),
            )
        )
        .scalars()
        .all()
    )
    found = {r.full_name.lower(): r for r in rows}
    ignored = [n for n in wanted if n not in found]
    keep = [found[n] for n in wanted if n in found][: settings.linked_repos_max]
    names = dir_names(r.full_name for r in keep)
    specs = tuple(
        LinkedRepoSpec(name, r.full_name, repo_ref(r), wanted[r.full_name.lower()])
        for name, r in zip(names, keep, strict=True)
    )
    return specs, ignored


def server_configs(s: Session, crypto: Crypto, org_id: UUID, limit: int) -> list[McpServerConfig]:
    rows = (
        s.execute(
            select(McpServer)
            .where(McpServer.org_id == org_id, McpServer.enabled.is_(True))
            .order_by(McpServer.name)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    out: list[McpServerConfig] = []
    for r in rows:
        if not r.allowed_tools:
            continue
        try:
            headers = decode_headers(crypto, r.headers_enc)
        except (DecryptionError, ValueError):
            log.warning("mcp_headers_undecryptable", server=r.name)
            continue
        out.append(
            McpServerConfig(
                r.name,
                r.url,
                headers,
                tuple(str(t) for t in r.allowed_tools),
                tuple(d for d in r.discovered_tools if isinstance(d, dict)),
            )
        )
    return out


def load_external_tools(
    s: Session, crypto: Crypto, settings: Settings, org_id: UUID, cfg: HootPRConfig
) -> ExternalTools | None:
    """The MCP + web-search tools this org/repo allows, or ``None`` when there are none."""
    kb = cfg.knowledge_base
    servers: list[McpServerConfig] = []
    if kb.mcp.usage != "disabled":
        servers = server_configs(s, crypto, org_id, settings.mcp_max_servers_per_org)
    cfg_search = search_config(settings) if kb.web_search.enabled else None
    search = WebSearch(cfg_search) if cfg_search is not None else None
    tools = ExternalTools.build(
        servers,
        search=search,
        timeout_s=settings.mcp_timeout_s,
        allow_http=settings.mcp_allow_http,
        allow_private=settings.mcp_allow_private_hosts,
        max_calls=settings.mcp_max_calls_per_review,
        max_output_kb=settings.mcp_max_output_kb,
        max_tools=settings.mcp_max_tools,
    )
    if not tools:
        tools.close()
        return None
    return tools


def discovered_payload(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]
