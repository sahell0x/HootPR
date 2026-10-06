import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.models import Membership, Organization, User
from tests.factories import make_identity, make_member, make_org, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration


@pytest.fixture
def org(db: Session) -> Organization:
    return make_org(db)


async def as_role(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization, role: str
) -> User:
    user = make_user(db, name=f"{role}-user", email=None)
    make_member(db, user, org, role=role)
    await login_as(client, app, user.id)
    return user


async def test_admin_updates_settings(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization
) -> None:
    await as_role(client, app, db, org, "admin")
    resp = await client.put(
        "/api/orgs/acme/settings",
        json={"settings": {"reviews": {"poem": True}}, "knowledge_base_opt_out": True},
    )
    assert resp.status_code == 200
    got = (await client.get("/api/orgs/acme/settings")).json()
    assert got == {"settings": {"reviews": {"poem": True}}, "knowledge_base_opt_out": True}


async def test_invalid_settings_rejected(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization
) -> None:
    await as_role(client, app, db, org, "admin")
    resp = await client.put(
        "/api/orgs/acme/settings", json={"settings": {"reviews": {"profile": "x"}}}
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_settings" and detail["errors"][0]["path"] == "reviews.profile"


async def test_member_cannot_update_settings(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization
) -> None:
    await as_role(client, app, db, org, "member")
    resp = await client.put("/api/orgs/acme/settings", json={"settings": {}})
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "forbidden"
    assert (await client.get("/api/orgs/acme/settings")).status_code == 200


async def test_members_list_and_role_change(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization, crypto: Crypto
) -> None:
    admin = await as_role(client, app, db, org, "admin")
    make_identity(db, crypto, admin, username="boss")
    bob = make_user(db, name="Bob", email=None)
    make_member(db, bob, org, role="member")
    members = (await client.get("/api/orgs/acme/members")).json()["members"]
    assert {m["display_name"]: m["role"] for m in members} == {
        "admin-user": "admin",
        "Bob": "member",
    }
    assert next(m for m in members if m["display_name"] == "admin-user")["username"] == "boss"
    resp = await client.patch(f"/api/orgs/acme/members/{bob.id}", json={"role": "billing_admin"})
    assert resp.status_code == 200 and resp.json()["role"] == "billing_admin"
    m = db.execute(select(Membership).where(Membership.user_id == bob.id)).scalar_one()
    db.refresh(m)
    assert m.role_manual is True  # provider re-sync must not undo it


async def test_member_cannot_change_roles(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization
) -> None:
    me = await as_role(client, app, db, org, "member")
    resp = await client.patch(f"/api/orgs/acme/members/{me.id}", json={"role": "admin"})
    assert resp.status_code == 403


async def test_cannot_demote_last_admin(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization
) -> None:
    admin = await as_role(client, app, db, org, "admin")
    resp = await client.patch(f"/api/orgs/acme/members/{admin.id}", json={"role": "member"})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "last_admin"


async def test_role_change_for_user_outside_org_is_404(
    client: httpx.AsyncClient, app: FastAPI, db: Session, org: Organization
) -> None:
    await as_role(client, app, db, org, "admin")
    stranger = make_user(db, name="S", email=None)
    resp = await client.patch(f"/api/orgs/acme/members/{stranger.id}", json={"role": "member"})
    assert resp.status_code == 404
