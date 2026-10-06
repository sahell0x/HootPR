from urllib.parse import unquote

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.models import CreditLedgerEntry, Installation, Membership, Organization
from tests.factories import make_identity, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration
API = "https://api.github.com"


def mock_installation(mock: respx.MockRouter, account_id: int = 9001, login: str = "acme") -> None:
    mock.get(f"{API}/app/installations/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 42,
                "account": {
                    "id": account_id,
                    "login": login,
                    "type": "Organization",
                    "avatar_url": None,
                },
            },
        )
    )


async def signed_in(client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto) -> None:
    user = make_user(db)
    make_identity(db, crypto, user)
    await login_as(client, app, user.id)


async def test_setup_requires_login(client: httpx.AsyncClient) -> None:
    resp = await client.get(
        "/api/github/setup", params={"installation_id": 42, "setup_action": "install"}
    )
    assert resp.status_code == 302
    assert (
        unquote(resp.headers["location"])
        == "http://localhost:3000/login?next=/api/github/setup?installation_id=42"
    )


async def test_setup_links_installation_and_redirects(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    await signed_in(client, app, db, crypto)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock_installation(mock)
        mock.get(f"{API}/user/memberships/orgs").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "role": "admin",
                        "organization": {"id": 9001, "login": "acme", "avatar_url": None},
                    }
                ],
            )
        )
        resp = await client.get("/api/github/setup", params={"installation_id": 42})
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:3000/o/acme/repos"
    org = db.execute(select(Organization)).scalar_one()
    assert db.execute(select(Installation)).scalar_one().github_installation_id == 42
    assert db.execute(select(Membership)).scalar_one().role == "admin"
    assert app.state.queue.calls == [("installations.sync_github", (42,))]
    assert org.slug == "acme"
    bonus = db.execute(select(CreditLedgerEntry)).scalars().all()
    assert [b.reason for b in bonus] == ["signup_bonus"]


async def test_setup_for_personal_account(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    await signed_in(client, app, db, crypto)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock_installation(mock, account_id=501, login="alice")
        resp = await client.get("/api/github/setup", params={"installation_id": 42})
    assert resp.headers["location"] == "http://localhost:3000/o/alice/repos"
    org = db.execute(select(Organization)).scalar_one()
    assert org.kind == "personal"


async def test_setup_for_org_user_is_not_member_of(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    await signed_in(client, app, db, crypto)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock_installation(mock)
        mock.get(f"{API}/user/memberships/orgs").mock(return_value=httpx.Response(200, json=[]))
        resp = await client.get("/api/github/setup", params={"installation_id": 42})
    assert resp.headers["location"] == "http://localhost:3000/orgs?error=not_a_member"
    assert db.execute(select(Installation)).first() is None
    assert app.state.queue.calls == []


async def test_setup_with_unknown_installation(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    await signed_in(client, app, db, crypto)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.get(f"{API}/app/installations/42").mock(return_value=httpx.Response(404))
        resp = await client.get("/api/github/setup", params={"installation_id": 42})
    assert resp.headers["location"] == "http://localhost:3000/orgs?error=installation_not_found"


async def test_setup_request_without_installation_goes_to_org_picker(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    await signed_in(client, app, db, crypto)
    resp = await client.get("/api/github/setup", params={"setup_action": "request"})
    assert resp.headers["location"] == "http://localhost:3000/orgs"
