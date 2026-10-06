import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.models import Installation, Organization, Repository, Review, User
from tests.factories import make_installation, make_member, make_org, make_pr, make_repo, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration

Setup = tuple[Organization, Installation, Repository, User]


@pytest.fixture
async def setup(client: httpx.AsyncClient, app: FastAPI, db: Session) -> Setup:
    org = make_org(db)
    inst = make_installation(db, org)
    repo = make_repo(db, org, inst)
    user = make_user(db)
    make_member(db, user, org, role="admin")
    await login_as(client, app, user.id)
    return org, inst, repo, user


async def test_list_repos(client: httpx.AsyncClient, setup: Setup) -> None:
    body = (await client.get("/api/orgs/acme/repos")).json()
    assert body["repos"][0]["full_name"] == "acme/web" and body["repos"][0]["enabled"] is True
    assert body["repos"][0]["last_review_at"] is None
    assert body["can_install"] is True
    assert body["install_url"].endswith("/installations/new/permissions?target_id=9001")


async def test_list_hides_detached_repos_and_shows_last_review(
    client: httpx.AsyncClient, setup: Setup, db: Session
) -> None:
    org, _, repo, _ = setup
    make_repo(db, org, None, provider_repo_id="1002", full_name="acme/old")
    pr = make_pr(db, repo)
    db.add(
        Review(pr_id=pr.id, org_id=org.id, head_sha=pr.head_sha, trigger="auto", status="completed")
    )
    db.commit()
    repos = (await client.get("/api/orgs/acme/repos")).json()["repos"]
    assert [r["full_name"] for r in repos] == ["acme/web"]
    assert repos[0]["last_review_at"] is not None


async def test_toggle_repo_and_settings(client: httpx.AsyncClient, setup: Setup) -> None:
    _, _, repo, _ = setup
    resp = await client.patch(f"/api/orgs/acme/repos/{repo.id}", json={"enabled": False})
    assert resp.status_code == 200 and resp.json()["enabled"] is False
    put = await client.put(
        f"/api/orgs/acme/repos/{repo.id}/settings",
        json={"settings": {"reviews": {"auto_review": {"drafts": True}}}},
    )
    assert put.status_code == 200
    got = (await client.get(f"/api/orgs/acme/repos/{repo.id}/settings")).json()
    assert got["settings"] == {"reviews": {"auto_review": {"drafts": True}}}
    assert got["repo"]["id"] == str(repo.id)


async def test_invalid_repo_settings(client: httpx.AsyncClient, setup: Setup) -> None:
    _, _, repo, _ = setup
    resp = await client.put(
        f"/api/orgs/acme/repos/{repo.id}/settings", json={"settings": {"nope": 1}}
    )
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_settings"


async def test_member_cannot_toggle(
    client: httpx.AsyncClient, app: FastAPI, setup: Setup, db: Session
) -> None:
    org, _, repo, _ = setup
    m = make_user(db, name="m", email=None)
    make_member(db, m, org, role="member")
    await login_as(client, app, m.id)
    resp = await client.patch(f"/api/orgs/acme/repos/{repo.id}", json={"enabled": False})
    assert resp.status_code == 403
    listed = (await client.get("/api/orgs/acme/repos")).json()
    assert listed["can_install"] is False


async def test_repo_of_another_org_is_404(
    client: httpx.AsyncClient, setup: Setup, db: Session
) -> None:
    other = make_org(db, slug="other", provider_org_id="1234")
    foreign = make_repo(db, other, provider_repo_id="999", full_name="other/x")
    assert (await client.get(f"/api/orgs/acme/repos/{foreign.id}/settings")).status_code == 404
    resp = await client.patch(f"/api/orgs/acme/repos/{foreign.id}", json={"enabled": False})
    assert resp.status_code == 404


async def test_sync_enqueues_installation_sync(
    client: httpx.AsyncClient, app: FastAPI, setup: Setup
) -> None:
    resp = await client.post("/api/orgs/acme/repos/sync")
    assert resp.status_code == 202 and resp.json() == {"status": "queued"}
    assert app.state.queue.calls == [("installations.sync_github", (42,))]


async def test_sync_without_installation_is_409(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    org = make_org(db)
    user = make_user(db)
    make_member(db, user, org, role="admin")
    await login_as(client, app, user.id)
    resp = await client.post("/api/orgs/acme/repos/sync")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "not_installed"
