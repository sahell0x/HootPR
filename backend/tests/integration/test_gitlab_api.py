import json

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.models import Installation, Organization, Repository
from tests.factories import make_installation, make_member, make_org, make_repo, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration
API = "https://gitlab.com/api/v4"
PROJECTS = [
    {
        "id": 2002,
        "path_with_namespace": "acme-group/api",
        "default_branch": "main",
        "visibility": "private",
    },
    {
        "id": 2003,
        "path_with_namespace": "acme-group/web",
        "default_branch": "dev",
        "visibility": "public",
    },
]


@pytest.fixture
async def gl_admin(client: httpx.AsyncClient, app: FastAPI, db: Session) -> Organization:
    org = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-acme-group", kind="group")
    user = make_user(db)
    make_member(db, user, org, role="admin")
    await login_as(client, app, user.id)
    return org


def _mock() -> respx.MockRouter:
    mock = respx.mock(assert_all_mocked=False, assert_all_called=False)
    mock.route(host="testserver").pass_through()
    return mock


async def test_connect_bot_validates_and_encrypts(
    client: httpx.AsyncClient, gl_admin: Organization, db: Session, crypto: Crypto
) -> None:
    assert (await client.get("/api/orgs/gl-acme-group/gitlab/bot")).json()["connected"] is False
    with _mock() as mock:
        mock.get(f"{API}/user").mock(
            return_value=httpx.Response(200, json={"id": 5, "username": "hootpr-bot"})
        )
        resp = await client.put("/api/orgs/gl-acme-group/gitlab/bot", json={"token": "glpat-good"})
    assert resp.json() == {"connected": True, "bot_username": "hootpr-bot", "bot_user_id": 5}
    inst = db.execute(select(Installation)).scalar_one()
    assert inst.gitlab_bot_token_enc and crypto.decrypt(inst.gitlab_bot_token_enc) == "glpat-good"
    assert "glpat-good" not in inst.gitlab_bot_token_enc
    got = (await client.get("/api/orgs/gl-acme-group/gitlab/bot")).json()
    assert got == {"connected": True, "bot_username": "hootpr-bot", "bot_user_id": 5}


async def test_bad_bot_token(client: httpx.AsyncClient, gl_admin: Organization) -> None:
    with _mock() as mock:
        mock.get(f"{API}/user").mock(return_value=httpx.Response(401))
        resp = await client.put("/api/orgs/gl-acme-group/gitlab/bot", json={"token": "bad"})
    assert resp.status_code == 400 and resp.json()["detail"]["code"] == "invalid_token"


async def test_projects_require_bot(client: httpx.AsyncClient, gl_admin: Organization) -> None:
    resp = await client.get("/api/orgs/gl-acme-group/gitlab/projects")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "not_installed"


async def test_select_projects_installs_hooks(
    client: httpx.AsyncClient, gl_admin: Organization, db: Session, crypto: Crypto
) -> None:
    with _mock() as mock:
        mock.get(f"{API}/user").mock(
            return_value=httpx.Response(200, json={"id": 5, "username": "hootpr-bot"})
        )
        await client.put("/api/orgs/gl-acme-group/gitlab/bot", json={"token": "glpat-good"})
        mock.get(f"{API}/groups/10/projects").mock(return_value=httpx.Response(200, json=PROJECTS))
        listed = (await client.get("/api/orgs/gl-acme-group/gitlab/projects")).json()
        assert [p["selected"] for p in listed["projects"]] == [False, False]
        mock.get(f"{API}/projects/2002/hooks").mock(return_value=httpx.Response(200, json=[]))
        hook = mock.post(f"{API}/projects/2002/hooks").mock(
            return_value=httpx.Response(201, json={"id": 31})
        )
        resp = await client.put(
            "/api/orgs/gl-acme-group/gitlab/projects",
            json={"project_ids": [2002], "whole_group": False},
        )
        listed = (await client.get("/api/orgs/gl-acme-group/gitlab/projects")).json()
    assert resp.status_code == 200
    assert [r["full_name"] for r in resp.json()["repos"]] == ["acme-group/api"]
    assert [p["selected"] for p in listed["projects"]] == [True, False]
    sent = json.loads(hook.calls[0].request.content)
    assert sent["url"] == "http://localhost:8000/api/webhooks/gitlab"
    repo = db.execute(select(Repository)).scalar_one()
    assert (
        repo.gitlab_hook_id == 31 and crypto.decrypt(repo.webhook_secret_enc or "") == sent["token"]
    )
    assert repo.private is True


async def test_deselect_removes_hook_and_whole_group(
    client: httpx.AsyncClient, gl_admin: Organization, db: Session, crypto: Crypto
) -> None:
    inst = make_installation(db, gl_admin, gitlab_token="glpat-x", crypto=crypto)
    make_repo(
        db,
        gl_admin,
        inst,
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme-group/api",
        webhook_secret="keep-me",
        crypto=crypto,
    )
    db.execute(select(Repository)).scalar_one().gitlab_hook_id = 31
    db.commit()
    with _mock() as mock:
        mock.get(f"{API}/groups/10/projects").mock(return_value=httpx.Response(200, json=PROJECTS))
        mock.get(f"{API}/projects/2002/hooks").mock(
            return_value=httpx.Response(
                200, json=[{"id": 31, "url": "http://localhost:8000/api/webhooks/gitlab"}]
            )
        )
        put_existing = mock.put(f"{API}/projects/2002/hooks/31").mock(
            return_value=httpx.Response(200, json={"id": 31})
        )
        mock.get(f"{API}/projects/2003/hooks").mock(return_value=httpx.Response(200, json=[]))
        mock.post(f"{API}/projects/2003/hooks").mock(
            return_value=httpx.Response(201, json={"id": 32})
        )
        resp = await client.put(
            "/api/orgs/gl-acme-group/gitlab/projects", json={"project_ids": [], "whole_group": True}
        )
        assert resp.status_code == 200
        assert [r["full_name"] for r in resp.json()["repos"]] == [
            "acme-group/api",
            "acme-group/web",
        ]
        # existing secret is reused (hook updated in place)
        assert json.loads(put_existing.calls[0].request.content)["token"] == "keep-me"
        removed = mock.delete(f"{API}/projects/2002/hooks/31").mock(
            return_value=httpx.Response(204)
        )
        resp = await client.put(
            "/api/orgs/gl-acme-group/gitlab/projects",
            json={"project_ids": [2003], "whole_group": False},
        )
    assert removed.called
    assert [r["full_name"] for r in resp.json()["repos"]] == ["acme-group/web"]
    db.expire_all()
    api_repo = db.execute(
        select(Repository).where(Repository.provider_repo_id == "2002")
    ).scalar_one()
    assert api_repo.installation_id is None and api_repo.enabled is False
    assert db.execute(select(Installation)).scalar_one().gitlab_whole_group is False


async def test_disconnect_bot_removes_hooks(
    client: httpx.AsyncClient, gl_admin: Organization, db: Session, crypto: Crypto
) -> None:
    inst = make_installation(db, gl_admin, gitlab_token="glpat-x", crypto=crypto)
    r = make_repo(
        db,
        gl_admin,
        inst,
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme-group/api",
        webhook_secret="s",
        crypto=crypto,
    )
    r.gitlab_hook_id = 31
    db.commit()
    with _mock() as mock:
        removed = mock.delete(f"{API}/projects/2002/hooks/31").mock(
            return_value=httpx.Response(404)
        )  # already gone: still detaches
        resp = await client.delete("/api/orgs/gl-acme-group/gitlab/bot")
    assert resp.status_code == 204 and removed.called
    db.expire_all()
    inst_row = db.execute(select(Installation)).scalar_one()
    assert inst_row.gitlab_bot_token_enc is None and inst_row.status == "revoked"
    assert db.execute(select(Repository)).scalar_one().installation_id is None
    assert (await client.get("/api/orgs/gl-acme-group/gitlab/bot")).json()["connected"] is False


async def test_bot_endpoints_reject_github_orgs(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    org = make_org(db)
    user = make_user(db, name="x", email=None)
    make_member(db, user, org, role="admin")
    await login_as(client, app, user.id)
    resp = await client.put("/api/orgs/acme/gitlab/bot", json={"token": "t"})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "wrong_provider"
