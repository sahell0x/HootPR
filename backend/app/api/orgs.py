"""Organization discovery, selection and the org switcher (spec §6.2)."""

from decimal import Decimal
from functools import partial
from typing import cast

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.api.meta import github_install_url
from app.api.schemas import (
    Org,
    OrgCandidate,
    OrgCandidateList,
    OrgKind,
    OrgList,
    Provider,
    Role,
    SelectOrgRequest,
)
from app.auth.provider_clients import OAuthError, OrgCandidateData, ReauthRequired
from app.billing.ledger import CreditLedger
from app.billing.pricing import CREDIT
from app.deps import (
    CurrentUser,
    Db,
    GitHubUsers,
    GitLabUsers,
    OrgContext,
    OrgMember,
    SettingsDep,
    Tokens,
)
from app.errors import api_error
from app.models import Identity, Membership, Organization, User
from app.orgs.service import ensure_organization, org_installed, upsert_membership

router = APIRouter(tags=["orgs"])


def reauth_error() -> HTTPException:
    return api_error(401, "reauth_required", "Your sign-in expired; sign in again")


async def org_out(db: Db, ctx: OrgContext) -> Org:
    o = ctx.org
    installed = await db.run_sync(lambda s: org_installed(s, o))
    return Org(
        id=str(o.id),
        slug=o.slug,
        provider=cast(Provider, o.provider),
        kind=cast(OrgKind, o.kind),
        name=o.name,
        avatar_url=o.avatar_url,
        role=cast(Role, ctx.role),
        credits_balance=Decimal(o.credits_balance).quantize(CREDIT),
        installed=installed,
        knowledge_base_opt_out=o.knowledge_base_opt_out,
    )


async def _identities(db: Db, user: User) -> list[Identity]:
    stmt = select(Identity).where(Identity.user_id == user.id).order_by(Identity.created_at)
    return list((await db.execute(stmt)).scalars())


@router.get("/api/orgs/candidates", response_model=OrgCandidateList)
async def candidates(
    user: CurrentUser,
    db: Db,
    tokens: Tokens,
    gh: GitHubUsers,
    gl: GitLabUsers,
    settings: SettingsDep,
) -> OrgCandidateList:
    found: list[OrgCandidateData] = []
    try:
        for ident in await _identities(db, user):
            if ident.provider == "github":
                found += await tokens.call(ident, gh.candidates)
            else:
                found += await tokens.call(
                    ident, partial(gl.candidates, user_id=ident.provider_user_id)
                )
    except ReauthRequired as exc:
        raise reauth_error() from exc
    except OAuthError as exc:
        raise api_error(502, "provider_error", "The provider API returned an error") from exc

    keys = [(c.provider, c.provider_org_id) for c in found]
    known: dict[tuple[str, str], tuple[Organization, str | None]] = {}
    if keys:
        rows = (
            await db.execute(
                select(Organization, Membership.role)
                .outerjoin(
                    Membership,
                    (Membership.org_id == Organization.id) & (Membership.user_id == user.id),
                )
                .where(tuple_(Organization.provider, Organization.provider_org_id).in_(keys))
            )
        ).all()
        known = {(o.provider, o.provider_org_id): (o, r) for o, r in rows}

    out: list[OrgCandidate] = []
    for c in found:
        org, role = known.get((c.provider, c.provider_org_id), (None, None))
        installed = c.installed
        if c.provider == "gitlab" and org is not None:
            installed = await db.run_sync(org_installed, org)
        install_url = None
        if c.provider == "github" and not installed:
            install_url = (
                f"{github_install_url(settings)}/permissions?target_id={c.provider_org_id}"
            )
        out.append(
            OrgCandidate(
                provider=cast(Provider, c.provider),
                provider_org_id=c.provider_org_id,
                kind=cast(OrgKind, c.kind),
                name=c.name,
                avatar_url=c.avatar_url,
                slug=org.slug if org is not None and role else None,
                joined=role is not None,
                installed=installed,
                role=cast(Role | None, role),
                install_url=install_url,
            )
        )
    return OrgCandidateList(orgs=out)


@router.get("/api/orgs", response_model=OrgList)
async def list_orgs(user: CurrentUser, db: Db) -> OrgList:
    rows = (
        await db.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user.id)
            .order_by(Organization.name, Organization.slug)
        )
    ).all()
    return OrgList(orgs=[await org_out(db, OrgContext(user, o, r)) for o, r in rows])


@router.post("/api/orgs/select", response_model=Org)
async def select_org(
    body: SelectOrgRequest,
    user: CurrentUser,
    db: Db,
    tokens: Tokens,
    gh: GitHubUsers,
    gl: GitLabUsers,
    settings: SettingsDep,
) -> Org:
    """Join (and on first use create) an org the user belongs to on the provider."""
    ident = next((i for i in await _identities(db, user) if i.provider == body.provider), None)
    if ident is None:
        raise api_error(403, "forbidden", f"Connect your {body.provider} account first")
    kind: str
    name: str
    path: str
    avatar: str | None
    role: str
    personal_id = (
        ident.provider_user_id if body.provider == "github" else f"user:{ident.provider_user_id}"
    )
    try:
        if body.provider_org_id == personal_id:
            kind, name, path, avatar, role = (
                "personal",
                ident.username,
                ident.username,
                user.avatar_url,
                "admin",
            )
        elif body.provider == "github":
            member = await tokens.call(ident, lambda t: gh.org_membership(t, body.provider_org_id))
            if member is None:
                raise api_error(403, "forbidden", "You are not a member of this organization")
            org_json, role = member
            login = str(org_json["login"])
            kind, name, path, avatar = "org", login, login, org_json.get("avatar_url")
        else:
            uid = ident.provider_user_id
            group = await tokens.call(ident, lambda t: gl.group(t, body.provider_org_id))
            role_hint = await tokens.call(
                ident, lambda t: gl.group_role(t, body.provider_org_id, uid)
            )
            if group is None or role_hint is None:
                raise api_error(403, "forbidden", "You are not a member of this group")
            kind, role = "group", role_hint
            name = str(group.get("full_name") or group["name"])
            path, avatar = str(group["full_path"]), group.get("avatar_url")
    except ReauthRequired as exc:
        raise reauth_error() from exc
    except OAuthError as exc:
        raise api_error(502, "provider_error", "The provider API returned an error") from exc

    def _tx(s: Session) -> tuple[Organization, str]:
        org, _ = ensure_organization(
            s,
            CreditLedger(),
            settings,
            provider=body.provider,
            provider_org_id=body.provider_org_id,
            kind=kind,
            name=name,
            path=path,
            avatar_url=avatar,
        )
        m = upsert_membership(s, user.id, org.id, role)
        return org, m.role

    org, final_role = await db.run_sync(_tx)
    await db.commit()
    return await org_out(db, OrgContext(user, org, final_role))


@router.get("/api/orgs/{org_slug}", response_model=Org)
async def get_org(ctx: OrgMember, db: Db) -> Org:
    return await org_out(db, ctx)
