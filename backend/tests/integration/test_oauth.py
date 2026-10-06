from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.models import Identity, User
from tests.factories import make_identity, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration
GH = "https://github.com"
GH_API = "https://api.github.com"
GL = "https://gitlab.com"


def mock_github_user(mock: respx.MockRouter, user_id: int = 501, login: str = "alice") -> None:
    mock.post(f"{GH}/login/oauth/access_token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "ghu_abc", "refresh_token": "ghr_abc", "expires_in": 28800}
        )
    )
    mock.get(f"{GH_API}/user").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": user_id,
                "login": login,
                "name": "Alice A",
                "avatar_url": "https://a/1.png",
            },
        )
    )
    mock.get(f"{GH_API}/user/emails").mock(
        return_value=httpx.Response(
            200, json=[{"email": "alice@example.com", "primary": True, "verified": True}]
        )
    )


async def start_login(
    client: httpx.AsyncClient, provider: str, next_: str = "/orgs"
) -> dict[str, list[str]]:
    resp = await client.get(f"/api/auth/{provider}/login", params={"next": next_})
    assert resp.status_code == 302
    return parse_qs(urlparse(resp.headers["location"]).query)


async def test_github_login_creates_user_and_session(
    client: httpx.AsyncClient, db: Session, crypto: Crypto
) -> None:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        q = await start_login(client, "github", "/o/acme/repos")
        assert q["client_id"] == ["gh-client"]
        assert q["redirect_uri"] == ["http://localhost:8000/api/auth/github/callback"]
        mock_github_user(mock)
        resp = await client.get(
            "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:3000/o/acme/repos"
    assert "hootpr_session" in resp.cookies and "hootpr_csrf" in resp.cookies
    ident = db.execute(select(Identity)).scalar_one()
    assert ident.username == "alice" and crypto.decrypt(ident.access_token_enc or "") == "ghu_abc"
    assert crypto.decrypt(ident.refresh_token_enc or "") == "ghr_abc"
    assert ident.token_expires_at is not None
    user = db.get(User, ident.user_id)
    assert user is not None and user.email == "alice@example.com"
    assert user.display_name == "Alice A"
    me = await client.get("/api/me")
    assert me.json()["identities"][0]["username"] == "alice"


async def test_second_login_reuses_user_and_refreshes_token(
    client: httpx.AsyncClient, db: Session, crypto: Crypto
) -> None:
    for _ in range(2):
        with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
            mock.route(host="testserver").pass_through()
            q = await start_login(client, "github")
            mock_github_user(mock)
            await client.get(
                "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
            )
    assert len(db.execute(select(User)).scalars().all()) == 1
    assert len(db.execute(select(Identity)).scalars().all()) == 1


async def test_callback_with_bad_state_redirects_with_error(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/auth/github/callback", params={"code": "c", "state": "nope"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:3000/login?error=oauth_state_invalid"


async def test_callback_state_for_other_provider_is_invalid(client: httpx.AsyncClient) -> None:
    q = await start_login(client, "github")
    resp = await client.get(
        "/api/auth/gitlab/callback", params={"code": "c", "state": q["state"][0]}
    )
    assert resp.headers["location"].endswith("error=oauth_state_invalid")


async def test_state_is_single_use(client: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        q = await start_login(client, "github")
        mock_github_user(mock)
        await client.get("/api/auth/github/callback", params={"code": "c", "state": q["state"][0]})
        again = await client.get(
            "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
        )
    assert again.headers["location"].endswith("error=oauth_state_invalid")


async def test_token_exchange_failure_redirects_oauth_failed(client: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        q = await start_login(client, "github")
        mock.post(f"{GH}/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "bad_verification_code"})
        )
        resp = await client.get(
            "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
        )
    assert resp.headers["location"] == "http://localhost:3000/login?error=oauth_failed"
    assert "hootpr_session" not in resp.cookies


async def test_provider_error_param_redirects_oauth_failed(client: httpx.AsyncClient) -> None:
    q = await start_login(client, "github")
    resp = await client.get(
        "/api/auth/github/callback", params={"error": "access_denied", "state": q["state"][0]}
    )
    assert resp.headers["location"].endswith("error=oauth_failed")


async def test_login_rejects_offsite_next(client: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        q = await start_login(client, "github", "https://evil.example/")
        mock_github_user(mock)
        resp = await client.get(
            "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
        )
    assert resp.headers["location"] == "http://localhost:3000/orgs"


async def test_gitlab_login_uses_pkce_and_links_to_signed_in_user(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    user = make_user(db)
    make_identity(db, crypto, user)
    await login_as(client, app, user.id)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        q = await start_login(client, "gitlab")
        assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["read_user read_api"]
        assert q["code_challenge"][0]
        token = mock.post(f"{GL}/oauth/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "gl_at", "refresh_token": "gl_rt", "expires_in": 7200}
            )
        )
        mock.get(f"{GL}/api/v4/user").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 77,
                    "username": "carol",
                    "name": "Carol",
                    "email": "c@example.com",
                    "avatar_url": None,
                },
            )
        )
        resp = await client.get(
            "/api/auth/gitlab/callback", params={"code": "c", "state": q["state"][0]}
        )
        assert resp.status_code == 302 and "error" not in resp.headers["location"]
        assert b"code_verifier=" in token.calls[0].request.content
    idents = db.execute(select(Identity).where(Identity.user_id == user.id)).scalars().all()
    assert sorted(i.provider for i in idents) == ["github", "gitlab"]


async def test_linking_identity_owned_by_someone_else_fails(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    other = make_user(db, name="Other", email=None)
    make_identity(db, crypto, other, provider="github", provider_user_id="501")
    me = make_user(db, name="Me", email=None)
    make_identity(db, crypto, me, provider="gitlab", provider_user_id="77", username="carol")
    await login_as(client, app, me.id)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        q = await start_login(client, "github")
        mock_github_user(mock)
        resp = await client.get(
            "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
        )
    assert resp.headers["location"] == "http://localhost:3000/login?error=identity_in_use"
    owner = db.execute(select(Identity).where(Identity.provider == "github")).scalar_one()
    assert owner.user_id == other.id


async def test_signing_in_with_other_account_of_same_provider_switches_user(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    me = make_user(db, name="Me", email=None)
    make_identity(db, crypto, me, provider="github", provider_user_id="999", username="me")
    await login_as(client, app, me.id)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        q = await start_login(client, "github")
        mock_github_user(mock)
        resp = await client.get(
            "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
        )
    assert "error" not in resp.headers["location"]
    alice = db.execute(select(Identity).where(Identity.provider_user_id == "501")).scalar_one()
    assert alice.user_id != me.id
    assert len(db.execute(select(Identity).where(Identity.user_id == me.id)).all()) == 1
    assert (await client.get("/api/me")).json()["identities"][0]["username"] == "alice"


async def test_callback_requires_the_browser_that_started_the_flow(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    """Login CSRF / identity-hijack: a state minted in another browser must be refused."""
    q = await start_login(client, "github")
    victim = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    async with victim:
        with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
            mock.route(host="testserver").pass_through()
            mock_github_user(mock)
            resp = await victim.get(
                "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
            )
    assert resp.headers["location"].endswith("error=oauth_state_invalid")
    assert "hootpr_session" not in resp.cookies
    assert db.execute(select(Identity)).first() is None


async def test_login_sets_httponly_nonce_cookie_and_callback_clears_it(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/auth/github/login")
    cookie = resp.headers["set-cookie"]
    assert "hootpr_oauth=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock_github_user(mock)
        state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
        done = await client.get("/api/auth/github/callback", params={"code": "c", "state": state})
    assert "error" not in done.headers["location"]
    assert 'hootpr_oauth=""' in done.headers.get("set-cookie", "") or "hootpr_oauth=;" in (
        done.headers.get("set-cookie", "")
    )


async def test_link_flow_refused_when_session_changed(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    """A link state minted for user A must not attach an identity while signed in as user B."""
    a = make_user(db, name="A", email=None)
    make_identity(db, crypto, a, provider="gitlab", provider_user_id="1", username="a")
    b = make_user(db, name="B", email=None)
    make_identity(db, crypto, b, provider="gitlab", provider_user_id="2", username="b")
    await login_as(client, app, a.id)
    q = await start_login(client, "github")
    await login_as(client, app, b.id)
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock_github_user(mock)
        resp = await client.get(
            "/api/auth/github/callback", params={"code": "c", "state": q["state"][0]}
        )
    assert resp.headers["location"].endswith("error=oauth_state_invalid")
    assert db.execute(select(Identity).where(Identity.provider == "github")).first() is None


async def test_login_for_unconfigured_provider_says_so(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    from app.deps import get_gitlab_user_client

    class Off:
        enabled = False

    app.dependency_overrides[get_gitlab_user_client] = lambda: Off()
    try:
        resp = await client.get("/api/auth/gitlab/login")
    finally:
        app.dependency_overrides.pop(get_gitlab_user_client, None)
    assert resp.headers["location"].endswith("error=provider_not_configured")
