"""MCP server registry (spec §10.4): members list, admins create/edit/delete/discover.

Auth headers are Fernet-encrypted at rest and never returned (only their names). URLs pass the
SSRF guard on every write and again before every outbound call.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import DecryptionError
from app.deps import CryptoDep, Db, OrgAdmin, OrgContext, OrgMember, SettingsDep
from app.errors import api_error
from app.kb.external import SERVER_NAME_RE
from app.kb.mcp_client import McpClient, McpError, McpPolicy
from app.kb.resolve import decode_headers, discovered_payload, encode_headers
from app.kb.ssrf import UnsafeUrl, check_url
from app.models import McpServer
from app.settings import Settings

router = APIRouter()
MAX_HEADERS = 10
HEADER_NAME_MAX = 100
HEADER_VALUE_MAX = 4096
FORBIDDEN_HEADERS = frozenset(
    {"host", "content-length", "content-type", "accept", "mcp-session-id", "mcp-protocol-version",
     "transfer-encoding", "connection", "cookie"}
)  # fmt: skip


class McpToolInfo(BaseModel):
    name: str
    description: str = ""


class McpServerOut(BaseModel):
    id: str
    name: str
    url: str
    header_names: list[str]
    allowed_tools: list[str]
    discovered_tools: list[McpToolInfo]
    enabled: bool
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime


class McpServerList(BaseModel):
    servers: list[McpServerOut]
    max_servers: int


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    url: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool = True


class McpServerUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    # None keeps the stored headers; {} removes them.
    headers: dict[str, str] | None = None
    allowed_tools: list[str] | None = Field(default=None, max_length=100)
    enabled: bool | None = None


def _out(row: McpServer, crypto_names: list[str]) -> McpServerOut:
    return McpServerOut(
        id=str(row.id),
        name=row.name,
        url=row.url,
        header_names=crypto_names,
        allowed_tools=list(row.allowed_tools or []),
        discovered_tools=[
            McpToolInfo(name=str(d.get("name")), description=str(d.get("description") or ""))
            for d in row.discovered_tools or []
            if isinstance(d, dict) and d.get("name")
        ],
        enabled=row.enabled,
        last_error=row.last_error,
        last_checked_at=row.last_checked_at,
        created_at=row.created_at,
    )


def _header_names(crypto: Any, row: McpServer) -> list[str]:
    try:
        return sorted(decode_headers(crypto, row.headers_enc))
    except (DecryptionError, ValueError):
        return []


def _clean_headers(headers: dict[str, str]) -> dict[str, str]:
    if len(headers) > MAX_HEADERS:
        raise api_error(422, "invalid_headers", f"at most {MAX_HEADERS} headers")
    out: dict[str, str] = {}
    for k, v in headers.items():
        name = k.strip()
        if (
            not name
            or len(name) > HEADER_NAME_MAX
            or not all(c.isalnum() or c in "-_" for c in name)
            or name.lower() in FORBIDDEN_HEADERS
        ):
            raise api_error(422, "invalid_headers", f"header name not allowed: {name[:40]!r}")
        if len(v) > HEADER_VALUE_MAX or "\n" in v or "\r" in v:
            raise api_error(422, "invalid_headers", f"invalid value for header {name}")
        out[name] = v
    return out


def _clean_tools(tools: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip()[:128] for t in tools if t.strip()))


async def _check_url(url: str, settings: Settings) -> str:
    try:
        return await asyncio.to_thread(
            check_url,
            url.strip(),
            allow_http=settings.mcp_allow_http,
            allow_private=settings.mcp_allow_private_hosts,
        )
    except UnsafeUrl as exc:
        raise api_error(422, "unsafe_url", str(exc)) from exc


async def _own(db: AsyncSession, ctx: OrgContext, server_id: UUID) -> McpServer:
    stmt = select(McpServer).where(McpServer.id == server_id, McpServer.org_id == ctx.org.id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise api_error(404, "not_found", "MCP server not found")
    return row


@router.get("/api/orgs/{org_slug}/mcp-servers", response_model=McpServerList)
async def list_servers(
    ctx: OrgMember, db: Db, crypto: CryptoDep, settings: SettingsDep
) -> McpServerList:
    rows = (
        (
            await db.execute(
                select(McpServer).where(McpServer.org_id == ctx.org.id).order_by(McpServer.name)
            )
        )
        .scalars()
        .all()
    )
    return McpServerList(
        servers=[_out(r, _header_names(crypto, r)) for r in rows],
        max_servers=settings.mcp_max_servers_per_org,
    )


@router.post("/api/orgs/{org_slug}/mcp-servers", response_model=McpServerOut, status_code=201)
async def create_server(
    body: McpServerCreate, ctx: OrgAdmin, db: Db, crypto: CryptoDep, settings: SettingsDep
) -> McpServerOut:
    name = body.name.strip().lower()
    if not SERVER_NAME_RE.match(name):
        raise api_error(
            422, "invalid_name", "use lowercase letters, digits and dashes (max 32 characters)"
        )
    count = (
        await db.execute(select(func.count()).where(McpServer.org_id == ctx.org.id))
    ).scalar_one()
    if count >= settings.mcp_max_servers_per_org:
        raise api_error(409, "limit_reached", "MCP server limit reached for this organization")
    dup = await db.execute(
        select(McpServer.id).where(McpServer.org_id == ctx.org.id, McpServer.name == name)
    )
    if dup.first() is not None:
        raise api_error(409, "duplicate_name", "an MCP server with this name exists")
    url = await _check_url(body.url, settings)
    headers = _clean_headers(body.headers)
    row = McpServer(
        org_id=ctx.org.id,
        name=name,
        url=url,
        headers_enc=encode_headers(crypto, headers),
        allowed_tools=_clean_tools(body.allowed_tools),
        discovered_tools=[],
        enabled=body.enabled,
        created_by=ctx.user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row, sorted(headers))


@router.patch("/api/orgs/{org_slug}/mcp-servers/{server_id}", response_model=McpServerOut)
async def update_server(
    server_id: UUID,
    body: McpServerUpdate,
    ctx: OrgAdmin,
    db: Db,
    crypto: CryptoDep,
    settings: SettingsDep,
) -> McpServerOut:
    row = await _own(db, ctx, server_id)
    if body.url is not None and body.url.strip() != row.url:
        row.url = await _check_url(body.url, settings)
        row.discovered_tools, row.last_error, row.last_checked_at = [], None, None
    if body.headers is not None:
        row.headers_enc = encode_headers(crypto, _clean_headers(body.headers))
    if body.allowed_tools is not None:
        row.allowed_tools = _clean_tools(body.allowed_tools)
    if body.enabled is not None:
        row.enabled = body.enabled
    await db.commit()
    await db.refresh(row)
    return _out(row, _header_names(crypto, row))


@router.delete("/api/orgs/{org_slug}/mcp-servers/{server_id}", status_code=204)
async def delete_server(server_id: UUID, ctx: OrgAdmin, db: Db) -> Response:
    row = await _own(db, ctx, server_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.post("/api/orgs/{org_slug}/mcp-servers/{server_id}/discover", response_model=McpServerOut)
async def discover_tools(
    server_id: UUID, ctx: OrgAdmin, db: Db, crypto: CryptoDep, settings: SettingsDep
) -> McpServerOut:
    """Connect to the server (from the API process, SSRF-guarded) and cache its tool list."""
    row = await _own(db, ctx, server_id)
    try:
        headers = decode_headers(crypto, row.headers_enc)
    except (DecryptionError, ValueError):
        headers = {}
    policy = McpPolicy(
        settings.mcp_allow_http, settings.mcp_allow_private_hosts, settings.mcp_timeout_s
    )

    def run() -> list[dict[str, Any]]:
        with McpClient(row.url, headers, policy) as client:
            return discovered_payload(client.list_tools())

    try:
        row.discovered_tools = await asyncio.to_thread(run)
        row.last_error = None
    except McpError as exc:
        row.last_error = str(exc)[:500]
    row.last_checked_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return _out(row, sorted(headers))
