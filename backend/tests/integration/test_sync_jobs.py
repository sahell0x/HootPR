from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.models import Repository
from app.orgs.sync_jobs import sync_github_installation, sync_gitlab_orgs
from app.platforms.base import PlatformError
from app.worker.context import WorkerContext
from tests.factories import make_installation, make_org, make_repo

pytestmark = pytest.mark.integration


class FakeAdmin:
    def __init__(self, projects: list[dict[str, Any]], fail: bool = False) -> None:
        self.projects, self.fail = projects, fail
        self.hooks: list[tuple[int, str]] = []
        self.closed = False

    def list_group_projects(self, group_id: str) -> list[dict[str, Any]]:
        if self.fail:
            raise PlatformError(401, "bot token revoked")
        return self.projects

    def install_hook(self, project_id: int, url: str, secret: str) -> int:
        self.hooks.append((project_id, url))
        return 900 + project_id

    def remove_hook(self, project_id: int, hook_id: int) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_sync_github_installation(db: Session, make_wctx: Callable[..., WorkerContext]) -> None:
    org = make_org(db)
    make_installation(db, org)
    repos = [{"id": 1001, "full_name": "acme/web", "private": True, "default_branch": "main"}]
    assert sync_github_installation(make_wctx(github_repos=lambda iid: repos), 42) == 1
    assert sync_github_installation(make_wctx(), 999) == 0
    assert db.execute(select(Repository)).scalar_one().full_name == "acme/web"


def test_sync_gitlab_whole_group_picks_up_new_projects(
    db: Session, crypto: Crypto, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-acme", kind="group")
    inst = make_installation(
        db, org, github_installation_id=None, gitlab_token="glpat", crypto=crypto
    )
    inst.gitlab_whole_group = True
    db.commit()
    admin = FakeAdmin([{"id": 2002, "path_with_namespace": "acme/api", "default_branch": "main"}])
    tokens: list[str] = []

    def factory(token: str) -> FakeAdmin:
        tokens.append(token)
        return admin

    assert sync_gitlab_orgs(make_wctx(gitlab_admin=factory)) == 1
    assert tokens == ["glpat"] and admin.closed
    repo = db.execute(select(Repository)).scalar_one()
    assert (repo.full_name, repo.gitlab_hook_id) == ("acme/api", 2902)


def test_sync_gitlab_selected_only_and_errors_skip_org(
    db: Session, crypto: Crypto, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-acme", kind="group")
    inst = make_installation(
        db, org, github_installation_id=None, gitlab_token="glpat", crypto=crypto
    )
    make_repo(db, org, inst, provider="gitlab", provider_repo_id="2002", full_name="acme/api")
    projects = [
        {"id": 2002, "path_with_namespace": "acme/api"},
        {"id": 2003, "path_with_namespace": "acme/other"},
    ]
    admin = FakeAdmin(projects)
    assert sync_gitlab_orgs(make_wctx(gitlab_admin=lambda t: admin), str(org.id)) == 1
    assert [h[0] for h in admin.hooks] == [2002]
    assert sync_gitlab_orgs(make_wctx(gitlab_admin=lambda t: FakeAdmin([], fail=True))) == 0
    assert sync_gitlab_orgs(make_wctx(gitlab_admin=lambda t: admin), "other-org") == 0


def test_sync_gitlab_does_not_steal_project_attached_to_another_org(
    db: Session, crypto: Crypto, make_wctx: Callable[..., WorkerContext]
) -> None:
    """A group org and its connected subgroup both list the subgroup's projects; the hourly
    sync must not flip the project between orgs or rewrite the other org's hook secret."""
    sub = make_org(db, provider="gitlab", provider_org_id="11", slug="gl-sub", kind="group")
    sub_inst = make_installation(
        db, sub, github_installation_id=None, gitlab_token="glpat-sub", crypto=crypto
    )
    repo = make_repo(
        db,
        sub,
        sub_inst,
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme/sub/api",
        webhook_secret="sub-secret",
        crypto=crypto,
    )
    parent = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-acme", kind="group")
    parent_inst = make_installation(
        db, parent, github_installation_id=None, gitlab_token="glpat", crypto=crypto
    )
    parent_inst.gitlab_whole_group = True
    db.commit()
    projects = [
        {"id": 2002, "path_with_namespace": "acme/sub/api"},
        {"id": 2003, "path_with_namespace": "acme/web"},
    ]
    admins = {"glpat": FakeAdmin(projects), "glpat-sub": FakeAdmin([])}
    sync_gitlab_orgs(make_wctx(gitlab_admin=lambda t: admins[t]), str(parent.id))
    assert [h[0] for h in admins["glpat"].hooks] == [2003]
    db.refresh(repo)
    assert repo.org_id == sub.id and repo.installation_id == sub_inst.id
    assert crypto.decrypt(repo.webhook_secret_enc or "") == "sub-secret"
    other = db.execute(select(Repository).where(Repository.provider_repo_id == "2003")).scalar_one()
    assert other.org_id == parent.id
