"""Org admin: public API keys and the audit log (spec §10.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.analytics import schemas as A
from app.analytics.api_keys import generate_key
from app.analytics.audit import audit
from app.deps import Db, OrgAdmin
from app.errors import api_error
from app.models import ApiKey, AuditLog

router = APIRouter()
MAX_ACTIVE_KEYS = 20


def key_out(k: ApiKey) -> A.ApiKeyOut:
    return A.ApiKeyOut(
        id=str(k.id),
        name=k.name,
        prefix=k.prefix,
        created_at=k.created_at,
        last_used_at=k.last_used_at,
        expires_at=k.expires_at,
        revoked_at=k.revoked_at,
    )


@router.get("/api/orgs/{org_slug}/api-keys", response_model=A.ApiKeyList)
async def list_keys(ctx: OrgAdmin, db: Db) -> A.ApiKeyList:
    rows = (
        await db.execute(
            select(ApiKey).where(ApiKey.org_id == ctx.org.id).order_by(ApiKey.created_at.desc())
        )
    ).scalars()
    return A.ApiKeyList(keys=[key_out(k) for k in rows])


@router.post("/api/orgs/{org_slug}/api-keys", response_model=A.ApiKeyCreated, status_code=201)
async def create_key(body: A.ApiKeyIn, ctx: OrgAdmin, db: Db) -> A.ApiKeyCreated:
    active = (
        await db.execute(
            select(ApiKey.id).where(ApiKey.org_id == ctx.org.id, ApiKey.revoked_at.is_(None))
        )
    ).all()
    if len(active) >= MAX_ACTIVE_KEYS:
        raise api_error(409, "too_many_keys", f"At most {MAX_ACTIVE_KEYS} active API keys")
    new = generate_key()
    k = ApiKey(
        org_id=ctx.org.id,
        name=body.name.strip(),
        prefix=new.prefix,
        key_hash=new.key_hash,
        created_by_user_id=ctx.user.id,
        expires_at=(
            datetime.now(UTC) + timedelta(days=body.expires_in_days)
            if body.expires_in_days
            else None
        ),
    )
    db.add(k)
    await db.flush()
    audit(
        db,
        ctx.org.id,
        "api_key.created",
        actor=ctx.user,
        target_type="api_key",
        target_id=k.id,
        details={"name": k.name, "prefix": k.prefix},
    )
    await db.commit()
    await db.refresh(k)
    return A.ApiKeyCreated(**key_out(k).model_dump(), secret=new.secret)


@router.delete("/api/orgs/{org_slug}/api-keys/{key_id}", status_code=204)
async def revoke_key(key_id: UUID, ctx: OrgAdmin, db: Db) -> Response:
    k = (
        await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == ctx.org.id))
    ).scalar_one_or_none()
    if k is None:
        raise api_error(404, "not_found", "API key not found")
    if k.revoked_at is None:
        k.revoked_at = datetime.now(UTC)
        audit(
            db,
            ctx.org.id,
            "api_key.revoked",
            actor=ctx.user,
            target_type="api_key",
            target_id=k.id,
            details={"name": k.name, "prefix": k.prefix},
        )
        await db.commit()
    return Response(status_code=204)


@router.get("/api/orgs/{org_slug}/audit-logs", response_model=A.AuditList)
async def audit_logs(
    ctx: OrgAdmin,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: datetime | None = None,
    action: str | None = None,
) -> A.AuditList:
    q = select(AuditLog).where(AuditLog.org_id == ctx.org.id)
    if before is not None:
        q = q.where(AuditLog.created_at < before)
    if action:
        esc = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.where(AuditLog.action.like(f"{esc}%", escape="\\"))
    rows = list(
        (
            await db.execute(
                q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return A.AuditList(
        entries=[
            A.AuditEntry(
                id=str(e.id),
                actor_label=e.actor_label,
                actor_user_id=str(e.actor_user_id) if e.actor_user_id else None,
                action=e.action,
                target_type=e.target_type,
                target_id=e.target_id,
                details=dict(e.details or {}),
                created_at=e.created_at,
            )
            for e in rows
        ],
        next_before=rows[-1].created_at if more and rows else None,
    )
