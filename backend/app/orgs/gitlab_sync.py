"""GitLab project selection + project hooks (spec §6.4). HTTP and DB steps are separate.

The API runs the HTTP half in a threadpool and the DB half through ``AsyncSession.run_sync``;
the hourly beat task (worker) runs both synchronously.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.crypto import Crypto, DecryptionError
from app.logging import get_logger
from app.models import Installation, Organization, Repository
from app.platforms.base import PlatformError
from app.platforms.gitlab.admin import GitLabAdmin

log = get_logger(__name__)


@dataclass(frozen=True)
class RepoSnapshot:
    provider_repo_id: str
    webhook_secret_enc: str | None
    gitlab_hook_id: int | None


@dataclass
class GitLabSyncPlan:
    # (project json, hook id, encrypted hook secret)
    upserts: list[tuple[dict[str, Any], int, str]] = field(default_factory=list)
    detach: list[RepoSnapshot] = field(default_factory=list)
    # Selected projects already attached to another org's active installation (skipped).
    conflicts: list[str] = field(default_factory=list)


def claimed_elsewhere_stmt(installation_id: UUID) -> Select[str]:
    """GitLab project ids attached to a *different* active installation.

    First attachment wins: a project is never silently moved between orgs (e.g. a group and a
    connected subgroup both list it), which would rewrite the other org's hook secret.
    """
    return (
        select(Repository.provider_repo_id)
        .join(Installation, Installation.id == Repository.installation_id)
        .where(
            Repository.provider == "gitlab",
            Installation.id != installation_id,
            Installation.status == "active",
        )
    )


def claimed_elsewhere(s: Session, installation_id: UUID) -> set[str]:
    return set(s.execute(claimed_elsewhere_stmt(installation_id)).scalars())


def snapshot(repo: Repository) -> RepoSnapshot:
    return RepoSnapshot(repo.provider_repo_id, repo.webhook_secret_enc, repo.gitlab_hook_id)


def list_org_projects(admin: GitLabAdmin, org: Organization) -> list[dict[str, Any]]:
    """Projects the bot can develop in: the group's (incl. subgroups) or a personal namespace's."""
    if org.provider_org_id.startswith("user:"):
        return admin.list_user_projects(org.provider_org_id.removeprefix("user:"))
    return admin.list_group_projects(org.provider_org_id)


def _secret_for(crypto: Crypto, snap: RepoSnapshot | None) -> tuple[str, str]:
    if snap is not None and snap.webhook_secret_enc:
        try:
            return crypto.decrypt(snap.webhook_secret_enc), snap.webhook_secret_enc
        except DecryptionError:
            pass  # key rotated: issue a fresh secret
    secret = secrets.token_urlsafe(32)
    return secret, crypto.encrypt(secret)


def install_hooks(
    admin: GitLabAdmin,
    crypto: Crypto,
    hook_url: str,
    existing: dict[str, RepoSnapshot],
    selected: list[dict[str, Any]],
    claimed: set[str] | frozenset[str] = frozenset(),
) -> GitLabSyncPlan:
    """HTTP only. Create/update hooks of ``selected``; remove hooks of deselected repos.

    ``existing`` must hold only repos currently attached to this installation; ``claimed`` the
    project ids attached to other orgs, which are skipped (``plan.conflicts``). Hook creation
    errors propagate (``PlatformError``); hook removal is best effort.
    """
    plan = GitLabSyncPlan()
    chosen = {str(p["id"]) for p in selected}
    for project in selected:
        if str(project["id"]) in claimed and str(project["id"]) not in existing:
            log.warning("gitlab_project_claimed_elsewhere", project_id=str(project["id"]))
            plan.conflicts.append(str(project["id"]))
            continue
        secret, secret_enc = _secret_for(crypto, existing.get(str(project["id"])))
        hook_id = admin.install_hook(int(project["id"]), hook_url, secret)
        plan.upserts.append((project, hook_id, secret_enc))
    for rid, snap in existing.items():
        if rid in chosen:
            continue
        if snap.gitlab_hook_id:
            try:
                admin.remove_hook(int(rid), snap.gitlab_hook_id)
            except PlatformError as exc:  # hook already gone or bot lost access; detach anyway
                log.warning("gitlab_hook_remove_failed", project_id=rid, error=str(exc))
        plan.detach.append(snap)
    return plan


def _by_project_id(s: Session, rid: str) -> Repository | None:
    return s.execute(
        select(Repository).where(
            Repository.provider == "gitlab", Repository.provider_repo_id == rid
        )
    ).scalar_one_or_none()


def apply_gitlab_sync(
    s: Session, installation: Installation, plan: GitLabSyncPlan
) -> list[Repository]:
    """DB only. Upsert selected projects as repositories; detach deselected ones.

    A project attached to another active installation is left alone (never reassigned).
    """
    out: list[Repository] = []
    for project, hook_id, secret_enc in plan.upserts:
        rid = str(project["id"])
        repo = _by_project_id(s, rid)
        if repo is not None and repo.installation_id not in (None, installation.id):
            other = s.get(Installation, repo.installation_id)
            if other is not None and other.status == "active":
                log.warning("gitlab_project_claimed_elsewhere", project_id=rid)
                continue
        if repo is None:
            repo = Repository(provider="gitlab", provider_repo_id=rid, settings={}, enabled=True)
            s.add(repo)
        elif repo.installation_id != installation.id:
            repo.enabled = True  # re-attached after being detached
        repo.org_id = installation.org_id
        repo.installation_id = installation.id
        repo.full_name = str(project["path_with_namespace"])
        repo.default_branch = str(project.get("default_branch") or "main")
        repo.private = project.get("visibility", "private") != "public"
        repo.gitlab_hook_id = hook_id
        repo.webhook_secret_enc = secret_enc
        out.append(repo)
    for snap in plan.detach:
        detached = _by_project_id(s, snap.provider_repo_id)
        if detached is not None:
            detached.installation_id = None
            detached.enabled = False
            detached.gitlab_hook_id = None
    s.flush()
    return out
