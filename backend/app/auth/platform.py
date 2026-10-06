"""Platform owners: the only viewers allowed to see internal LLM cost / token / model data.

End users only ever see HootPR credits; the platform pays for models. ``PLATFORM_OWNERS`` is a
comma-separated list of ``provider:username`` matched (case-insensitively) against the user's
linked identities.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Identity, User
from app.settings import Settings


def platform_owner_set(settings: Settings) -> frozenset[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for raw in settings.platform_owners.split(","):
        provider, sep, username = raw.strip().partition(":")
        if sep and provider.strip() and username.strip():
            out.add((provider.strip().lower(), username.strip().lower()))
    return frozenset(out)


async def is_platform_owner(db: AsyncSession, settings: Settings, user: User | None) -> bool:
    owners = platform_owner_set(settings)
    if user is None or not owners:
        return False
    rows = (
        await db.execute(
            select(Identity.provider, Identity.username).where(Identity.user_id == user.id)
        )
    ).all()
    return any((p.lower(), u.lower()) in owners for p, u in rows)


# Response fields that are internal (LLM cost / tokens). Stripped for everyone but platform
# owners; ``llm_calls`` (per-call model / tokens / cost / excerpts) is emptied.
INTERNAL_FIELDS = frozenset(
    {
        "input_tokens",
        "cached_tokens",
        "output_tokens",
        "cost_usd",
        "avg_tokens_per_review",
        "avg_cost_per_review",
        "usage_30d",
    }
)
INTERNAL_LISTS = frozenset({"llm_calls"})


def strip_internal[M: BaseModel](m: M) -> M:
    """A copy of a response model with every internal LLM field nulled (recursively)."""
    updates: dict[str, Any] = {}
    for name in type(m).model_fields:
        v = getattr(m, name)
        if name in INTERNAL_FIELDS:
            updates[name] = None
        elif name in INTERNAL_LISTS:
            updates[name] = []
        elif isinstance(v, BaseModel):
            updates[name] = strip_internal(v)
        elif isinstance(v, list) and any(isinstance(x, BaseModel) for x in v):
            updates[name] = [strip_internal(x) if isinstance(x, BaseModel) else x for x in v]
    return m.model_copy(update=updates)


def for_viewer[M: BaseModel](m: M, owner: bool) -> M:
    return m if owner else strip_internal(m)
