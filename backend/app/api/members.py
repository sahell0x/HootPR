"""Organization members and roles (spec §6.2): admin | member | billing_admin."""

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import Select, select

from app.analytics.audit import audit
from app.api.schemas import Member, MemberList, RoleUpdate
from app.deps import Db, OrgAdmin, OrgMember
from app.errors import api_error
from app.models import Identity, Membership, User

router = APIRouter()


def _members_query(org_id: UUID, provider: str) -> Select[User, str, str | None]:
    # Username of the identity for the org's provider (first linked one if several).
    username = (
        select(Identity.username)
        .where(Identity.user_id == User.id, Identity.provider == provider)
        .order_by(Identity.created_at)
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    return (
        select(User, Membership.role, username)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id)
    )


def _member_out(user: User, role: str, username: str | None) -> Member:
    return Member(
        user_id=str(user.id),
        display_name=user.display_name,
        username=username,
        avatar_url=user.avatar_url,
        role=role,
    )


@router.get("/api/orgs/{org_slug}/members", response_model=MemberList)
async def list_members(ctx: OrgMember, db: Db) -> MemberList:
    rows = (
        await db.execute(_members_query(ctx.org.id, ctx.org.provider).order_by(User.display_name))
    ).all()
    return MemberList(members=[_member_out(u, role, name) for u, role, name in rows])


@router.patch("/api/orgs/{org_slug}/members/{user_id}", response_model=Member)
async def update_role(user_id: UUID, body: RoleUpdate, ctx: OrgAdmin, db: Db) -> Member:
    # Lock every admin row of the org so two concurrent demotions can't remove the last admin.
    admins = (
        (
            await db.execute(
                select(Membership)
                .where(Membership.org_id == ctx.org.id, Membership.role == "admin")
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    m = (
        await db.execute(
            select(Membership)
            .where(Membership.org_id == ctx.org.id, Membership.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if m is None:
        raise api_error(404, "not_found", "Member not found")
    if m.role == "admin" and body.role != "admin" and len(admins) <= 1:
        raise api_error(409, "last_admin", "An organization needs at least one admin")
    if m.role != body.role:
        audit(
            db,
            ctx.org.id,
            "member.role_changed",
            actor=ctx.user,
            target_type="user",
            target_id=user_id,
            details={"from": m.role, "to": body.role},
        )
    m.role, m.role_manual = body.role, True
    await db.commit()
    row = (
        await db.execute(_members_query(ctx.org.id, ctx.org.provider).where(User.id == user_id))
    ).first()
    if row is None:  # pragma: no cover - deleted concurrently
        raise api_error(404, "not_found", "Member not found")
    return _member_out(row[0], row[1], row[2])
