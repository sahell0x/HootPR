import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.api.schemas import Health
from app.crypto import Crypto
from app.errors import api_error
from app.main import create_app
from app.settings import Settings
from app.worker.queue import CeleryTaskQueue


@pytest.fixture
async def offline_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """App wired to unreachable Postgres/Redis (settings fixture uses port 1)."""
    application = create_app(settings)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    await application.state.http.aclose()
    await application.state.redis.aclose()
    await application.state.async_engine.dispose()


def test_state_is_wired(settings: Settings) -> None:
    app: FastAPI = create_app(settings)
    assert app.state.settings is settings
    assert isinstance(app.state.crypto, Crypto)
    assert isinstance(app.state.queue, CeleryTaskQueue)
    assert app.title == "HootPR API"


async def test_health_is_degraded_when_backends_are_down(
    offline_client: httpx.AsyncClient,
) -> None:
    resp = await offline_client.get("/api/health")
    assert resp.status_code == 200
    body = Health.model_validate(resp.json())
    assert body.status == "degraded"
    assert body.checks.db == "error"
    assert body.checks.redis == "error"
    assert body.checks.docker_proxy == "unknown"  # heartbeat lives in the (down) Redis


def test_api_error_shape() -> None:
    exc = api_error(409, "last_admin", "Last admin", errors=[])
    assert exc.status_code == 409
    detail: object = exc.detail
    assert detail == {"code": "last_admin", "message": "Last admin", "errors": []}


def test_dev_secret_warning_is_logged(capsys: pytest.CaptureFixture[str]) -> None:
    create_app(Settings(_env_file=None, app_env="development"))
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    assert any("development secrets" in line["event"] for line in lines)


def test_no_dev_warning_with_real_secrets(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    create_app(settings.model_copy(update={"app_env": "development"}))
    assert "development secrets" not in capsys.readouterr().out


async def test_lifespan_closes_shared_clients(settings: Settings) -> None:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert not app.state.http.is_closed
    assert app.state.http.is_closed


async def test_cors_preflight_allows_only_the_dashboard_origin(
    offline_client: httpx.AsyncClient,
) -> None:
    req = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-csrf-token,content-type",
    }
    ok = await offline_client.options(
        "/api/orgs/select", headers={"Origin": "http://localhost:3000", **req}
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert ok.headers["access-control-allow-credentials"] == "true"
    assert "x-csrf-token" in ok.headers["access-control-allow-headers"].lower()
    bad = await offline_client.options(
        "/api/orgs/select", headers={"Origin": "https://evil.example", **req}
    )
    assert bad.status_code == 400
    assert "access-control-allow-origin" not in bad.headers


async def test_simple_request_from_other_origin_gets_no_cors_headers(
    offline_client: httpx.AsyncClient,
) -> None:
    resp = await offline_client.get("/api/auth/csrf", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers
    resp = await offline_client.get("/api/auth/csrf", headers={"Origin": "http://localhost:3000"})
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_csrf_endpoint_returns_token_and_sets_cookie(
    offline_client: httpx.AsyncClient,
) -> None:
    resp = await offline_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["csrf_token"]
    assert token and resp.cookies.get("hootpr_csrf") == token
    assert "samesite=lax" in resp.headers["set-cookie"].lower()
    again = await offline_client.get("/api/auth/csrf")  # cookie now present: reused, not reset
    assert again.json()["csrf_token"] == token and "set-cookie" not in again.headers


async def test_cookie_samesite_none_is_secure_with_domain(settings: Settings) -> None:
    s = settings.model_copy(update={"cookie_samesite": "none", "cookie_domain": ".example.com"})
    application = create_app(s)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        header = (await c.get("/api/auth/csrf")).headers["set-cookie"].lower()
    assert "samesite=none" in header and "secure" in header and "domain=.example.com" in header
    await application.state.http.aclose()
    await application.state.redis.aclose()
    await application.state.async_engine.dispose()


def test_oauth_redirect_uris_and_post_login_targets_use_the_right_origin(
    settings: Settings,
) -> None:
    from app.api.auth import post_login_url
    from app.auth.provider_clients import GitHubUserClient, GitLabUserClient

    http = httpx.AsyncClient()
    assert GitHubUserClient(settings, http).redirect_uri() == (
        "http://localhost:8000/api/auth/github/callback"
    )
    assert GitLabUserClient(settings, http).redirect_uri() == (
        "http://localhost:8000/api/auth/gitlab/callback"
    )
    assert post_login_url(settings, "/o/acme/repos") == "http://localhost:3000/o/acme/repos"
    assert post_login_url(settings, "/api/github/setup?installation_id=1") == (
        "http://localhost:8000/api/github/setup?installation_id=1"
    )
