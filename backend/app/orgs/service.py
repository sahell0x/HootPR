"""Organization creation (signup bonus), memberships and slugs (spec §6.2, decision P4)."""

import re
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid_utils.compat import uuid7

from app.billing.ledger import CreditLedger
from app.models import Installation, Membership, Organization
from app.models.base import utcnow
from app.settings import Settings

_MAX_SLUG_ATTEMPTS = 5


def make_slug(provider: str, path: str) -> str:
    """GitHub: ``login.lower()``; GitLab: ``gl-`` + full_path with ``/`` and ``.`` → ``-``."""
    base = re.sub(r"[^a-z0-9-]+", "-", path.lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base) or "org"
    return base if provider == "github" else f"gl-{base}"


def _unique_slug(s: Session, base: str) -> str:
    slug, n = base, 1
    while s.execute(select(exists().where(Organization.slug == slug))).scalar():
        n += 1
        slug = f"{base}-{n}"
    return slug


def _find(s: Session, provider: str, provider_org_id: str) -> Organization | None:
    return s.execute(
        select(Organization).where(
            Organization.provider == provider, Organization.provider_org_id == provider_org_id
        )
    ).scalar_one_or_none()


def ensure_organization(
    s: Session,
    ledger: CreditLedger,
    settings: Settings,
    *,
    provider: str,
    provider_org_id: str,
    kind: str,
    name: str,
    path: str,
    avatar_url: str | None,
) -> tuple[Organization, bool]:
    """Return the org, creating it (plus the one-time signup bonus) on first use.

    ``INSERT ... ON CONFLICT DO NOTHING`` makes concurrent first selections safe: exactly one
    transaction inserts the row and grants the bonus. A lost race on the *slug* (a different org
    grabbing the same slug) retries with the next free suffix.
    """
    for _ in range(_MAX_SLUG_ATTEMPTS):
        existing = _find(s, provider, provider_org_id)
        if existing is not None:
            existing.name = name
            existing.avatar_url = avatar_url or existing.avatar_url
            s.flush()
            return existing, False
        now = utcnow()
        stmt = (
            insert(Organization)
            .values(
                id=uuid7(),
                created_at=now,
                updated_at=now,
                provider=provider,
                provider_org_id=provider_org_id,
                kind=kind,
                name=name,
                slug=_unique_slug(s, make_slug(provider, path)),
                avatar_url=avatar_url,
                credits_balance=0,
                purchases_count=0,
                settings={},
                knowledge_base_opt_out=False,
                blocked=False,
            )
            .on_conflict_do_nothing()
            .returning(Organization.id)
        )
        new_id = s.execute(stmt).scalar_one_or_none()
        if new_id is None:
            continue  # same org inserted concurrently (found next loop) or slug taken (retry)
        org = s.execute(
            select(Organization)
            .where(Organization.id == new_id)
            .execution_options(populate_existing=True)
        ).scalar_one()
        if settings.credits_signup_bonus > 0:
            ledger.grant(
                s, org.id, settings.credits_signup_bonus, "signup_bonus", "organization", org.id
            )
        return org, True
    raise RuntimeError(f"could not allocate a slug for {provider}:{provider_org_id}")


def upsert_membership(s: Session, user_id: UUID, org_id: UUID, role: str) -> Membership:
    """Create or refresh the membership from the provider role.

    A role a HootPR admin assigned (``role_manual``, incl. every ``billing_admin``, spec §6.2) is
    never overwritten by the provider-derived role; only provider-derived roles are re-synced.
    """
    m = s.execute(
        select(Membership).where(Membership.user_id == user_id, Membership.org_id == org_id)
    ).scalar_one_or_none()
    if m is None:
        m = Membership(user_id=user_id, org_id=org_id, role=role)
        s.add(m)
    elif not m.role_manual and not (m.role == "billing_admin" and role == "member"):
        m.role = role
    s.flush()
    return m


def org_installed(s: Session, org: Organization) -> bool:
    """GitHub: an active App installation; GitLab: a connected bot token."""
    stmt = select(
        exists().where(
            Installation.org_id == org.id,
            Installation.status == "active",
            (Installation.github_installation_id.is_not(None))
            | (Installation.gitlab_bot_token_enc.is_not(None)),
        )
    )
    return bool(s.execute(stmt).scalar())
