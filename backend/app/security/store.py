"""Sync DB helpers for security scans (worker side)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SecurityScan

KINDS = ("surface_map", "security_review")
ACTIVE = ("queued", "running")
REF_TYPE = "security_scan"
TASK = "security.run"
MAX_BASELINE_ENTRIES = 2000


def latest_surface_scan(s: Session, repo_id: UUID) -> SecurityScan | None:
    """The newest completed scan (either kind) that stored an attack surface map."""
    return (
        s.execute(
            select(SecurityScan)
            .where(SecurityScan.repo_id == repo_id, SecurityScan.status == "completed")
            .order_by(SecurityScan.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def surface_baseline(s: Session, repo_id: UUID) -> tuple[dict[str, Any], ...] | None:
    """Entry points of the latest stored map, for "attack surface changes" in PR walkthroughs.

    Never fails a review: any problem means "no baseline"."""
    try:
        scan = latest_surface_scan(s, repo_id)
    except Exception:
        return None
    if scan is None:
        return None
    surface = (scan.result or {}).get("surface")
    if not isinstance(surface, dict):
        return None
    eps = surface.get("entry_points")
    if not isinstance(eps, list):
        return None
    return tuple(e for e in eps[:MAX_BASELINE_ENTRIES] if isinstance(e, dict))


def active_scan(s: Session, repo_id: UUID, kind: str) -> SecurityScan | None:
    return (
        s.execute(
            select(SecurityScan)
            .where(
                SecurityScan.repo_id == repo_id,
                SecurityScan.kind == kind,
                SecurityScan.status.in_(ACTIVE),
            )
            .order_by(SecurityScan.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
