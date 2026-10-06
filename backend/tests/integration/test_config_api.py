import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from tests.factories import make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration


async def test_schema_endpoint(client: httpx.AsyncClient) -> None:
    for path in ("/schema/hootpr.v1.json", "/api/schema/hootpr.v1.json"):
        resp = await client.get(path)
        assert resp.status_code == 200 and "reviews" in resp.json()["properties"]


async def test_schema_route_uses_api_base_url_and_caches(client: httpx.AsyncClient) -> None:
    for path in ("/schema/hootpr.v1.json", "/api/schema/hootpr.v1.json"):
        resp = await client.get(path)
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "public, max-age=3600"
        assert resp.json()["$id"] == "http://localhost:8000/schema/hootpr.v1.json"
        assert "ast_grep" in json.dumps(resp.json())


async def test_validate_requires_session(client: httpx.AsyncClient) -> None:
    client.cookies.set("hootpr_csrf", "x")
    resp = await client.post(
        "/api/config/validate", json={"yaml": ""}, headers={"X-CSRF-Token": "x"}
    )
    assert resp.status_code == 401


async def test_validate_endpoint(client: httpx.AsyncClient, app: FastAPI, db: Session) -> None:
    await login_as(client, app, make_user(db).id)
    ok = (
        await client.post("/api/config/validate", json={"yaml": "reviews:\n  poem: true\n"})
    ).json()
    assert ok["valid"] is True and ok["effective"]["reviews"]["poem"] is True and ok["errors"] == []
    bad = (
        await client.post("/api/config/validate", json={"yaml": "reviews:\n  profile: x\n"})
    ).json()
    assert bad["valid"] is False and bad["effective"] is None
    assert bad["errors"][0] == {
        "line": 2,
        "path": "reviews.profile",
        "message": bad["errors"][0]["message"],
    }
