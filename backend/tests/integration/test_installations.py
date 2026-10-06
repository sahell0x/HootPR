import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Installation, Repository
from app.orgs.installations import (
    remove_github_repositories,
    sync_github_repositories,
    upsert_github_installation,
)
from tests.factories import make_org

pytestmark = pytest.mark.integration


def test_sync_upserts_and_detaches(db: Session) -> None:
    org = make_org(db)
    inst = upsert_github_installation(db, org.id, 42)
    assert upsert_github_installation(db, org.id, 42).id == inst.id
    sync_github_repositories(
        db,
        inst,
        [
            {"id": 1001, "full_name": "acme/web", "private": True, "default_branch": "main"},
            {"id": 1002, "full_name": "acme/api", "private": False, "default_branch": "dev"},
        ],
        replace=True,
    )
    sync_github_repositories(
        db,
        inst,
        [{"id": 1001, "full_name": "acme/web2", "private": True, "default_branch": "main"}],
        replace=True,
    )
    db.commit()
    repos = {r.provider_repo_id: r for r in db.execute(select(Repository)).scalars()}
    assert repos["1001"].full_name == "acme/web2" and repos["1001"].installation_id == inst.id
    assert repos["1001"].enabled is True and repos["1001"].private is True
    assert repos["1002"].installation_id is None and repos["1002"].enabled is False
    assert repos["1002"].default_branch == "dev"


def test_reattached_repo_is_enabled_again(db: Session) -> None:
    org = make_org(db)
    inst = upsert_github_installation(db, org.id, 42)
    data = [{"id": 1001, "full_name": "acme/web", "private": True, "default_branch": "main"}]
    sync_github_repositories(db, inst, data, replace=True)
    remove_github_repositories(db, inst, ["1001"])
    repo = db.execute(select(Repository)).scalar_one()
    assert repo.installation_id is None and repo.enabled is False
    sync_github_repositories(db, inst, data, replace=False)
    assert repo.installation_id == inst.id and repo.enabled is True


def test_sync_without_replace_keeps_other_repos(db: Session) -> None:
    org = make_org(db)
    inst = upsert_github_installation(db, org.id, 42)
    sync_github_repositories(
        db, inst, [{"id": 1, "full_name": "acme/a", "default_branch": "main"}], replace=True
    )
    sync_github_repositories(
        db, inst, [{"id": 2, "full_name": "acme/b", "default_branch": "main"}], replace=False
    )
    repos = db.execute(select(Repository).where(Repository.installation_id == inst.id)).all()
    assert len(repos) == 2


def test_upsert_installation_updates_status_and_org(db: Session) -> None:
    a = make_org(db)
    b = make_org(db, provider_org_id="9002", slug="b", name="b")
    inst = upsert_github_installation(db, a.id, 42)
    again = upsert_github_installation(db, b.id, 42, status="suspended")
    db.commit()
    assert again.id == inst.id
    row = db.execute(select(Installation)).scalar_one()
    assert row.org_id == b.id and row.status == "suspended"
