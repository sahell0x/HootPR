"""GitHub installation rows and repository sync (spec §6.3). Sync functions; caller commits."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Installation, Repository


def upsert_github_installation(
    s: Session, org_id: UUID, installation_id: int, status: str = "active"
) -> Installation:
    inst = s.execute(
        select(Installation).where(Installation.github_installation_id == installation_id)
    ).scalar_one_or_none()
    if inst is None:
        inst = Installation(
            org_id=org_id,
            provider="github",
            github_installation_id=installation_id,
            status=status,
        )
        s.add(inst)
    else:
        inst.org_id = org_id
        inst.status = status
    s.flush()
    return inst


def _detach(repo: Repository) -> None:
    """The App lost access: keep history (reviews), stop reviewing."""
    repo.installation_id = None
    repo.enabled = False


def sync_github_repositories(
    s: Session, installation: Installation, repos: list[dict[str, Any]], *, replace: bool
) -> list[Repository]:
    """Upsert ``repos`` (GitHub repository JSON) under ``installation``.

    With ``replace=True`` the list is the full set the installation can access, so this
    installation's repos missing from it are detached.
    """
    existing = {
        r.provider_repo_id: r
        for r in s.execute(
            select(Repository).where(
                Repository.provider == "github",
                Repository.provider_repo_id.in_([str(d["id"]) for d in repos]),
            )
        ).scalars()
    }
    out: list[Repository] = []
    seen: set[str] = set()
    for data in repos:
        rid = str(data["id"])
        seen.add(rid)
        repo = existing.get(rid)
        if repo is None:
            repo = Repository(provider="github", provider_repo_id=rid, enabled=True, settings={})
            s.add(repo)
            existing[rid] = repo
        elif repo.installation_id is None:
            repo.enabled = True  # re-granted access
        repo.org_id = installation.org_id
        repo.installation_id = installation.id
        repo.full_name = str(data["full_name"])
        repo.private = bool(data.get("private", False))
        repo.default_branch = str(data.get("default_branch") or repo.default_branch or "main")
        out.append(repo)
    if replace:
        attached = s.execute(
            select(Repository).where(Repository.installation_id == installation.id)
        ).scalars()
        for repo in attached:
            if repo.provider_repo_id not in seen:
                _detach(repo)
    s.flush()
    return out


def remove_github_repositories(s: Session, installation: Installation, repo_ids: list[str]) -> None:
    if not repo_ids:
        return
    stmt = select(Repository).where(
        Repository.installation_id == installation.id, Repository.provider_repo_id.in_(repo_ids)
    )
    for repo in s.execute(stmt).scalars():
        _detach(repo)
    s.flush()
