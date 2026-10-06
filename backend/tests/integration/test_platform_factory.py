import pytest
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.platforms.factory import NotInstalled, make_platform_factory, repo_ref
from app.platforms.github.platform import GitHubPlatform
from app.platforms.gitlab.platform import GitLabPlatform
from app.settings import Settings
from tests.factories import make_installation, make_org, make_repo
from tests.fakes.kv import DictKV

pytestmark = pytest.mark.integration


def test_builds_provider_platforms(db: Session, settings: Settings, crypto: Crypto) -> None:
    factory = make_platform_factory(settings, DictKV({"gh:insttoken:42": "ghs"}), crypto)
    gh_org = make_org(db)
    gh_repo = make_repo(db, gh_org, make_installation(db, gh_org))
    assert isinstance(factory(db, gh_repo), GitHubPlatform)
    gl_org = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-x")
    gl_inst = make_installation(
        db, gl_org, github_installation_id=None, gitlab_token="glpat", crypto=crypto
    )
    gl_repo = make_repo(
        db, gl_org, gl_inst, provider="gitlab", provider_repo_id="2002", full_name="g/api"
    )
    assert isinstance(factory(db, gl_repo), GitLabPlatform)
    assert repo_ref(gl_repo).provider_repo_id == "2002"
    assert repo_ref(gl_repo).provider == "gitlab"
    orphan = make_repo(db, gh_org, None, provider_repo_id="5", full_name="acme/orphan")
    with pytest.raises(NotInstalled):
        factory(db, orphan)


def test_inactive_installation_is_not_installed(
    db: Session, settings: Settings, crypto: Crypto
) -> None:
    factory = make_platform_factory(settings, DictKV(), crypto)
    org = make_org(db)
    inst = make_installation(db, org)
    repo = make_repo(db, org, inst)
    inst.status = "suspended"
    db.commit()
    with pytest.raises(NotInstalled):
        factory(db, repo)
    gl_org = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-x")
    gl_inst = make_installation(db, gl_org, github_installation_id=None)  # no bot token
    gl_repo = make_repo(
        db, gl_org, gl_inst, provider="gitlab", provider_repo_id="3", full_name="g/x"
    )
    with pytest.raises(NotInstalled):
        factory(db, gl_repo)
