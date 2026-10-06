"""Audit log writers (spec §10.5). Rows are added to the caller's session; the caller commits
together with the change being audited, so an audited change and its record are atomic."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import AuditLog, User

MAX_DETAIL_CHARS = 500
SYSTEM = "system"


def _clip(v: Any) -> Any:
    if isinstance(v, str):
        return v if len(v) <= MAX_DETAIL_CHARS else v[:MAX_DETAIL_CHARS] + "…"
    if isinstance(v, dict):
        return {str(k): _clip(x) for k, x in list(v.items())[:50]}
    if isinstance(v, list | tuple):
        return [_clip(x) for x in list(v)[:50]]
    if isinstance(v, int | float | bool) or v is None:
        return v
    return _clip(str(v))


def changed_keys(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    """Top-level keys whose value differs (added, removed or changed), sorted."""
    b, a = before or {}, after or {}
    return sorted(k for k in set(b) | set(a) if b.get(k) != a.get(k))


def build(
    org_id: UUID,
    action: str,
    *,
    actor: User | None = None,
    actor_label: str | None = None,
    target_type: str | None = None,
    target_id: str | UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    label = actor_label or (actor.display_name if actor is not None else SYSTEM)
    return AuditLog(
        org_id=org_id,
        actor_user_id=actor.id if actor is not None else None,
        actor_label=label[:255],
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=_clip(details or {}),
    )


def audit(db: AsyncSession | Session, org_id: UUID, action: str, **kw: Any) -> None:
    """Stage one audit row in ``db`` (async API session or sync worker session)."""
    db.add(build(org_id, action, **kw))
