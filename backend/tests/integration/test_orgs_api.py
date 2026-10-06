from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.models import CreditLedgerEntry, Identity, Membership, Organization, User
from tests.factories import make_identity, make_installation, make_member, make_org, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration
GH = "https://github.com"
GH_API = "https://api.github.com"
GL_API = "https://gitlab.com/api/v4"


def gh_user_mocks(mock: respx.MockRouter) -> None:
    mock.get(f"{GH_API}/user").mock(
        return_value=httpx.Response(200, json={"id": 501, "login": "alice", "avatar_url": None})
    )
    mock.get(f"{GH_API}/user/installations").mock(
        return_value=httpx.Response(
            200,
            json={
                "installations": [
                    {"id": 42, "account": {"id": 9001, "login": "acme", "avatar_url": None}}
                ]
            },
        )
    )
    mock.get(f"{GH_API}/user/memberships/orgs").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "role": "admin",
                    "organization": {"id": 9001, "login": "acme", "avatar_url": None},
                },
                {
                    "role": "member",
                    "organization": {"id": 9002, "login": "other", "avatar_url": None},
                },
            ],
        )
    )


@pytest.fixture
async def alice(client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto) -> User:
    user = make_user(db)
    make_identity(db, crypto, user)
    await login_as(client, app, user.id)
    return user


async def test_candidates_require_session(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/orgs/candidates")
    assert resp.status_code == 401 and resp.json()["detail"]["code"] == "unauthenticated"


async def test_github_candidates(client: httpx.AsyncClient, alice: User, db: Session) -> None:
    joined = make_org(db, provider_org_id="9002", slug="other", name="other")
    make_member(db, alice, joined, role="member")
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        gh_user_mocks(mock)
        resp = await client.get("/api/orgs/candidates")
    assert resp.status_code == 200
    orgs = {o["name"]: o for o in resp.json()["orgs"]}
    assert orgs["alice"]["kind"] == "personal" and orgs["alice"]["installed"] is False
    assert orgs["alice"]["install_url"].startswith(
        "https://github.com/apps/hootpr-test/installations/new"
    )
    assert orgs["acme"]["installed"] is True and orgs["acme"]["role"] is None
    assert orgs["acme"]["joined"] is False and orgs["acme"]["install_url"] is None
    assert orgs["other"]["installed"] is False
    assert orgs["other"]["joined"] is True and orgs["other"]["slug"] == "other"
    assert orgs["other"]["role"] == "member"


async def test_gitlab_candidates(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    user = make_user(db)
    make_identity(db, crypto, user, provider="gitlab", provider_user_id="77", username="carol")
    await login_as(client, app, user.id)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.get(f"{GL_API}/user").mock(
            return_value=httpx.Response(200, json={"id": 77, "username": "carol"})
        )
        groups = mock.get(f"{GL_API}/groups").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 10, "name": "Acme", "full_name": "Acme", "full_path": "acme"}],
            )
        )
        resp = await client.get("/api/orgs/candidates")
    assert groups.calls[0].request.url.params["min_access_level"] == "40"
    orgs = resp.json()["orgs"]
    assert [(o["provider_org_id"], o["kind"]) for o in orgs] == [
        ("user:77", "personal"),
        ("10", "group"),
    ]
    assert all(o["install_url"] is None for o in orgs)


async def test_list_orgs_with_expired_github_token_returns_reauth_required(
    client: httpx.AsyncClient, alice: User
) -> None:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.get(f"{GH_API}/user").mock(return_value=httpx.Response(401))
        resp = await client.get("/api/orgs/candidates")
    assert resp.status_code == 401 and resp.json()["detail"]["code"] == "reauth_required"


async def test_expired_token_is_refreshed_with_refresh_token(
    client: httpx.AsyncClient, alice: User, db: Session, crypto: Crypto
) -> None:
    ident = db.execute(select(Identity)).scalar_one()
    ident.refresh_token_enc = crypto.encrypt("ghr_old")
    ident.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        refresh = mock.post(f"{GH}/login/oauth/access_token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "ghu_new", "refresh_token": "ghr_new", "expires_in": 28800},
            )
        )
        gh_user_mocks(mock)
        resp = await client.get("/api/orgs/candidates")
    assert resp.status_code == 200
    assert b"grant_type=refresh_token" in refresh.calls[0].request.content
    db.expire_all()
    ident = db.execute(select(Identity)).scalar_one()
    assert crypto.decrypt(ident.access_token_enc or "") == "ghu_new"
    assert crypto.decrypt(ident.refresh_token_enc or "") == "ghr_new"


async def test_failed_refresh_returns_reauth_required(
    client: httpx.AsyncClient, alice: User, db: Session, crypto: Crypto
) -> None:
    ident = db.execute(select(Identity)).scalar_one()
    ident.refresh_token_enc = crypto.encrypt("ghr_old")
    db.commit()
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.get(f"{GH_API}/user").mock(return_value=httpx.Response(401))
        mock.post(f"{GH}/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "bad_refresh_token"})
        )
        resp = await client.get("/api/orgs/candidates")
    assert resp.status_code == 401 and resp.json()["detail"]["code"] == "reauth_required"


async def test_select_github_org_creates_org_with_bonus_once(
    client: httpx.AsyncClient, alice: User, db: Session
) -> None:
    for _ in range(2):
        with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
            mock.route(host="testserver").pass_through()
            gh_user_mocks(mock)
            resp = await client.post(
                "/api/orgs/select", json={"provider": "github", "provider_org_id": "9001"}
            )
        assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "acme" and body["role"] == "admin" and body["credits_balance"] == "300"
    assert body["kind"] == "org" and body["installed"] is False
    org = db.execute(select(Organization)).scalar_one()
    bonuses = (
        db.execute(select(CreditLedgerEntry).where(CreditLedgerEntry.org_id == org.id))
        .scalars()
        .all()
    )
    assert [(b.reason, b.delta) for b in bonuses] == [("signup_bonus", Decimal("300"))]


async def test_select_org_as_plain_member(client: httpx.AsyncClient, alice: User) -> None:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        gh_user_mocks(mock)
        resp = await client.post(
            "/api/orgs/select", json={"provider": "github", "provider_org_id": "9002"}
        )
    assert resp.json()["role"] == "member" and resp.json()["slug"] == "other"


async def test_select_keeps_billing_admin(
    client: httpx.AsyncClient, alice: User, db: Session
) -> None:
    org = make_org(db, provider_org_id="9002", slug="other", name="other")
    make_member(db, alice, org, role="billing_admin")
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        gh_user_mocks(mock)
        resp = await client.post(
            "/api/orgs/select", json={"provider": "github", "provider_org_id": "9002"}
        )
    assert resp.json()["role"] == "billing_admin"


async def test_select_personal_account_is_admin(client: httpx.AsyncClient, alice: User) -> None:
    resp = await client.post(
        "/api/orgs/select", json={"provider": "github", "provider_org_id": "501"}
    )
    assert resp.json()["kind"] == "personal" and resp.json()["role"] == "admin"
    assert resp.json()["slug"] == "alice"


async def test_select_org_user_is_not_member_of_is_forbidden(
    client: httpx.AsyncClient, alice: User
) -> None:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        gh_user_mocks(mock)
        resp = await client.post(
            "/api/orgs/select", json={"provider": "github", "provider_org_id": "12345"}
        )
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "forbidden"


async def test_select_without_identity_for_provider_is_forbidden(
    client: httpx.AsyncClient, alice: User
) -> None:
    resp = await client.post(
        "/api/orgs/select", json={"provider": "gitlab", "provider_org_id": "10"}
    )
    assert resp.status_code == 403


async def test_select_gitlab_group_owner_is_admin_maintainer_is_member(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    user = make_user(db)
    make_identity(
        db, crypto, user, provider="gitlab", provider_user_id="77", username="carol", token="gl_at"
    )
    await login_as(client, app, user.id)
    for level, role in ((50, "admin"), (40, "member")):
        with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
            mock.route(host="testserver").pass_through()
            mock.get(f"{GL_API}/groups/10").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": 10,
                        "name": "Acme Group",
                        "full_name": "Acme Group",
                        "full_path": "acme-group",
                        "avatar_url": None,
                    },
                )
            )
            mock.get(f"{GL_API}/groups/10/members/all/77").mock(
                return_value=httpx.Response(200, json={"access_level": level})
            )
            resp = await client.post(
                "/api/orgs/select", json={"provider": "gitlab", "provider_org_id": "10"}
            )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "gl-acme-group"
        m = db.execute(select(Membership).where(Membership.user_id == user.id)).scalar_one()
        db.refresh(m)
        assert m.role == role


async def test_select_gitlab_personal_namespace(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    user = make_user(db)
    make_identity(db, crypto, user, provider="gitlab", provider_user_id="77", username="carol")
    await login_as(client, app, user.id)
    resp = await client.post(
        "/api/orgs/select", json={"provider": "gitlab", "provider_org_id": "user:77"}
    )
    body = resp.json()
    assert body["slug"] == "gl-carol" and body["kind"] == "personal" and body["role"] == "admin"


async def test_slug_collision_gets_suffix(
    client: httpx.AsyncClient, alice: User, db: Session
) -> None:
    make_org(db, provider="gitlab", provider_org_id="55", slug="acme")
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        gh_user_mocks(mock)
        resp = await client.post(
            "/api/orgs/select", json={"provider": "github", "provider_org_id": "9001"}
        )
    assert resp.json()["slug"] == "acme-2"


async def test_org_endpoints_hide_non_member_orgs(
    client: httpx.AsyncClient, alice: User, db: Session
) -> None:
    make_org(db, slug="secret", provider_org_id="7777")
    resp = await client.get("/api/orgs/secret")
    assert resp.status_code == 404 and resp.json()["detail"]["code"] == "not_found"
    assert (await client.get("/api/orgs/does-not-exist")).status_code == 404


async def test_list_and_get_joined_orgs(
    client: httpx.AsyncClient, alice: User, db: Session
) -> None:
    org = make_org(db, balance="2")
    make_member(db, alice, org, role="member")
    make_org(db, slug="notmine", provider_org_id="1234")
    listed = (await client.get("/api/orgs")).json()["orgs"]
    assert [o["slug"] for o in listed] == ["acme"]
    got = (await client.get("/api/orgs/acme")).json()
    assert got["role"] == "member" and got["credits_balance"] == "2" and got["installed"] is False
    make_installation(db, org)
    assert (await client.get("/api/orgs/acme")).json()["installed"] is True


def test_slugs() -> None:
    from app.orgs.service import make_slug

    assert make_slug("github", "Acme-Inc") == "acme-inc"
    assert make_slug("gitlab", "Acme/Sub.Group") == "gl-acme-sub-group"
    assert make_slug("github", "---") == "org"


@pytest.mark.parametrize(
    ("provider_org_id", "slug", "manual_role"),
    [("9001", "acme", "member"), ("9002", "other", "admin")],
)
async def test_select_keeps_manually_assigned_role(
    client: httpx.AsyncClient,
    alice: User,
    db: Session,
    provider_org_id: str,
    slug: str,
    manual_role: str,
) -> None:
    """A role set by a HootPR admin (PATCH /members) survives re-selecting the org."""
    org = make_org(db, provider_org_id=provider_org_id, slug=slug, name=slug)
    m = make_member(db, alice, org, role=manual_role)
    m.role_manual = True
    db.commit()
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        gh_user_mocks(mock)
        resp = await client.post(
            "/api/orgs/select", json={"provider": "github", "provider_org_id": provider_org_id}
        )
    assert resp.status_code == 200 and resp.json()["role"] == manual_role
