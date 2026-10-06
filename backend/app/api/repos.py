"""Repositories list/toggle, per-repo settings, and "Sync" (spec §6.3, §6.4, §9.1 level 2)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.analytics.audit import audit, changed_keys
from app.api.schemas import (
    EffectiveConfig,
    Repo,
    RepoList,
    RepoSettings,
    SettingsUpdate,
    UpdateRepoRequest,
)
from app.config.loader import resolve_config
from app.config.render import render_configuration
from app.config.validator import validate_settings
from app.deps import Db, OrgAdmin, OrgContext, OrgMember, SettingsDep, get_queue
from app.errors import api_error, invalid_settings_error
from app.models import Installation, Organization, PullRequest, Repository, Review
from app.settings import Settings

router = APIRouter()
YAML_FILE_NOTE = (
    "A .hootpr.yaml on the default branch overrides these settings "
    "(set inheritance: true in it to merge instead). "
    "Run @hootpr configuration on a pull request to see the configuration it uses."
)


def repo_out(r: Repository, last_review_at: datetime | None) -> Repo:
    return Repo(
        id=str(r.id),
        provider=r.provider,
        full_name=r.full_name,
        private=r.private,
        enabled=r.enabled,
        default_branch=r.default_branch,
        last_review_at=last_review_at,
    )


async def list_repos(db: Db, org: Organization) -> list[Repo]:
    """Repos currently attached to an installation of ``org`` (detached ones are hidden)."""
    last = (
        select(PullRequest.repo_id, func.max(Review.created_at).label("last"))
        .join(Review, Review.pr_id == PullRequest.id)
        .group_by(PullRequest.repo_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Repository, last.c.last)
            .outerjoin(last, last.c.repo_id == Repository.id)
            .where(Repository.org_id == org.id, Repository.installation_id.is_not(None))
            .order_by(Repository.full_name)
        )
    ).all()
    return [repo_out(r, ts) for r, ts in rows]


def install_url(org: Organization, settings: Settings) -> str | None:
    if org.provider != "github":
        return None
    return (
        f"{settings.github_web_url.rstrip('/')}/apps/{settings.github_app_slug}/installations/new"
        f"/permissions?target_id={org.provider_org_id}"
    )


async def _repo(db: Db, ctx: OrgContext, repo_id: UUID) -> Repository:
    repo = (
        await db.execute(
            select(Repository).where(Repository.id == repo_id, Repository.org_id == ctx.org.id)
        )
    ).scalar_one_or_none()
    if repo is None:
        raise api_error(404, "not_found", "Repository not found")
    return repo


async def _last_review(db: Db, repo_id: UUID) -> datetime | None:
    stmt = (
        select(func.max(Review.created_at))
        .join(PullRequest, PullRequest.id == Review.pr_id)
        .where(PullRequest.repo_id == repo_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("/api/orgs/{org_slug}/repos", response_model=RepoList)
async def repos(ctx: OrgMember, db: Db, settings: SettingsDep) -> RepoList:
    return RepoList(
        repos=await list_repos(db, ctx.org),
        can_install=ctx.role == "admin",
        install_url=install_url(ctx.org, settings),
    )


@router.patch("/api/orgs/{org_slug}/repos/{repo_id}", response_model=Repo)
async def update_repo(repo_id: UUID, body: UpdateRepoRequest, ctx: OrgAdmin, db: Db) -> Repo:
    repo = await _repo(db, ctx, repo_id)
    if repo.enabled != body.enabled:
        audit(
            db,
            ctx.org.id,
            "repo.enabled" if body.enabled else "repo.disabled",
            actor=ctx.user,
            target_type="repository",
            target_id=repo.id,
            details={"repo": repo.full_name},
        )
    repo.enabled = body.enabled
    await db.commit()
    return repo_out(repo, await _last_review(db, repo.id))


@router.get("/api/orgs/{org_slug}/repos/{repo_id}/settings", response_model=RepoSettings)
async def get_repo_settings(repo_id: UUID, ctx: OrgMember, db: Db) -> RepoSettings:
    repo = await _repo(db, ctx, repo_id)
    return RepoSettings(
        repo=repo_out(repo, await _last_review(db, repo.id)), settings=repo.settings or {}
    )


@router.put("/api/orgs/{org_slug}/repos/{repo_id}/settings", response_model=RepoSettings)
async def put_repo_settings(
    repo_id: UUID, body: SettingsUpdate, ctx: OrgAdmin, db: Db
) -> RepoSettings:
    issues = validate_settings(body.settings)
    if issues:
        raise invalid_settings_error(issues)
    repo = await _repo(db, ctx, repo_id)
    audit(
        db,
        ctx.org.id,
        "repo.settings_updated",
        actor=ctx.user,
        target_type="repository",
        target_id=repo.id,
        details={"repo": repo.full_name, "changed": changed_keys(repo.settings, body.settings)},
    )
    repo.settings = body.settings
    await db.commit()
    return RepoSettings(
        repo=repo_out(repo, await _last_review(db, repo.id)), settings=repo.settings
    )


@router.post("/api/orgs/{org_slug}/repos/sync", status_code=202)
async def sync(request: Request, ctx: OrgAdmin, db: Db) -> dict[str, str]:
    inst = (
        (
            await db.execute(
                select(Installation).where(
                    Installation.org_id == ctx.org.id, Installation.status == "active"
                )
            )
        )
        .scalars()
        .first()
    )
    if inst is None:
        raise api_error(409, "not_installed", "HootPR is not installed for this organization")
    if ctx.org.provider == "github" and inst.github_installation_id:
        get_queue(request).enqueue("installations.sync_github", inst.github_installation_id)
    else:
        get_queue(request).enqueue("gitlab.sync_hooks", str(ctx.org.id))
    return {"status": "queued"}


def _sources(
    provenance: dict[str, Literal["repo", "org"]],
) -> list[Literal["repo", "org", "default"]]:
    used = set(provenance.values())
    out: list[Literal["repo", "org", "default"]] = []
    if "repo" in used:
        out.append("repo")
    if "org" in used:
        out.append("org")
    out.append("default")
    return out


@router.get("/api/orgs/{org_slug}/repos/{repo_id}/effective-config", response_model=EffectiveConfig)
async def effective_config(repo_id: UUID, ctx: OrgMember, db: Db) -> EffectiveConfig:
    """Repo + org UI settings merged like a review would (without the repo's .hootpr.yaml)."""
    repo = await _repo(db, ctx, repo_id)
    resolved = resolve_config(None, repo.settings or None, ctx.org.settings or None)
    provenance: dict[str, Literal["repo", "org"]] = {
        path: "repo" if src == "repo" else "org"
        for path, src in resolved.provenance.items()
        if src in ("repo", "org")
    }
    return EffectiveConfig(
        config=resolved.config.model_dump(mode="json"),
        provenance=provenance,
        yaml=render_configuration(resolved),
        sources=_sources(provenance),
        yaml_file_note=YAML_FILE_NOTE,
    )
