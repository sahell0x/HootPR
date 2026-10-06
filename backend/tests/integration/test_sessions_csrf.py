import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session
from uuid_utils.compat import uuid7

from app.auth.sessions import SESSION_TTL_S, SessionStore
from app.crypto import Crypto
from tests.factories import make_identity, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration


async def test_session_store_sliding_ttl(app: FastAPI, db: Session) -> None:
    user = make_user(db)
    store: SessionStore = app.state.sessions
    sid = await store.create(user.id)
    assert len(sid) >= 43  # 256-bit urlsafe token
    key = store._key(sid)
    assert await app.state.redis.get(f"session:{sid}") is None  # raw id is never the key
    await app.state.redis.expire(key, 10)
    assert await store.user_id(sid) == user.id
    assert await app.state.redis.ttl(key) > SESSION_TTL_S - 5
    await store.destroy(sid)
    assert await store.user_id(sid) is None


async def test_me_requires_session(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "unauthenticated"


async def test_me_with_unknown_session_is_unauthenticated(client: httpx.AsyncClient) -> None:
    client.cookies.set("hootpr_session", "not-a-real-session")
    assert (await client.get("/api/me")).status_code == 401


async def test_me_with_session_of_deleted_user_is_unauthenticated(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    await login_as(client, app, uuid7())
    assert (await client.get("/api/me")).status_code == 401


async def test_me_returns_identities_and_csrf(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    user = make_user(db)
    make_identity(db, crypto, user)
    await login_as(client, app, user.id)
    client.cookies.delete("hootpr_csrf")
    resp = await client.get("/api/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Alice" and body["email"] == "alice@example.com"
    assert body["identities"] == [
        {"provider": "github", "provider_user_id": "501", "username": "alice"}
    ]
    assert body["csrf_token"] and resp.cookies.get("hootpr_csrf") == body["csrf_token"]


async def test_me_reuses_existing_csrf_cookie(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    user = make_user(db)
    await login_as(client, app, user.id)
    resp = await client.get("/api/me")
    assert resp.json()["csrf_token"] == "test-csrf"
    assert "hootpr_csrf" not in resp.cookies


async def test_mutations_require_csrf(client: httpx.AsyncClient, app: FastAPI, db: Session) -> None:
    user = make_user(db)
    await login_as(client, app, user.id)
    bad = await client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"})
    assert bad.status_code == 403 and bad.json()["detail"]["code"] == "csrf_failed"
    ok = await client.post("/api/auth/logout")
    assert ok.status_code == 204
    set_cookie = ok.headers.get_list("set-cookie")
    assert any(c.startswith("hootpr_session=") for c in set_cookie)
    assert any(c.startswith("hootpr_csrf=") for c in set_cookie)
    assert (await client.get("/api/me")).status_code == 401


async def test_mutation_without_csrf_header_is_rejected(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    user = make_user(db)
    await login_as(client, app, user.id)
    del client.headers["X-CSRF-Token"]
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 403


async def test_webhooks_are_csrf_exempt(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/webhooks/github", content=b"{}")
    assert resp.status_code != 403  # 401 (bad signature) or 404 until Task 23 exists
