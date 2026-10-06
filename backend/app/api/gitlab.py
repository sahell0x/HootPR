"""GitLab bot token + project selection (spec §6.4)."""

from collections.abc import Callable

from fastapi import APIRouter, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.analytics.audit import audit
from app.api.repos import list_repos
from app.api.schemas import (
    GitlabBot,
    GitlabBotRequest,
    GitlabProject,
    GitlabProjectList,
    GitlabProjectsRequest,
    RepoList,
)
from app.crypto import Crypto, DecryptionError
from app.deps import CryptoDep, Db, OrgAdmin, OrgContext, OrgMember, SettingsDep
from app.errors import api_error
from app.models import Installation, Repository
from app.orgs.gitlab_sync import (
    GitLabSyncPlan,
    apply_gitlab_sync,
    claimed_elsewhere_stmt,
    install_hooks,
    list_org_projects,
    snapshot,
)
from app.platforms.base import PlatformError
from app.platforms.gitlab.admin import GitLabAdmin
from app.settings import Settings

router = APIRouter()


def _require_gitlab(ctx: OrgContext) -> None:
    if ctx.org.provider != "gitlab":
        raise api_error(
            409, "wrong_provider", "GitLab bot settings apply to GitLab organizations only"
        )


async def _installation(db: Db, ctx: OrgContext) -> Installation | None:
    stmt = select(Installation).where(
        Installation.org_id == ctx.org.id, Installation.provider == "gitlab"
    )
    return (await db.execute(stmt)).scalars().first()


def _bot(inst: Installation | None) -> GitlabBot:
    if inst is None or not inst.gitlab_bot_token_enc or inst.status != "active":
        return GitlabBot(connected=False, bot_username=None, bot_user_id=None)
    return GitlabBot(
        connected=True, bot_username=inst.gitlab_bot_username, bot_user_id=inst.gitlab_bot_user_id
    )


async def _with_admin[T](token: str, settings: Settings, fn: Callable[[GitLabAdmin], T]) -> T:
    """Run blocking GitLab calls in a threadpool and always close the client."""

    def run() -> T:
        admin = GitLabAdmin(token, base_url=settings.gitlab_base_url)
        try:
            return fn(admin)
        finally:
            admin.close()

    return await run_in_threadpool(run)


def _provider_error(exc: PlatformError, what: str) -> Exception:
    return api_error(502, "provider_error", f"GitLab request failed while {what}: {exc}")


@router.get("/api/orgs/{org_slug}/gitlab/bot", response_model=GitlabBot)
async def get_bot(ctx: OrgMember, db: Db) -> GitlabBot:
    return _bot(await _installation(db, ctx))


@router.put("/api/orgs/{org_slug}/gitlab/bot", response_model=GitlabBot)
async def put_bot(
    body: GitlabBotRequest, ctx: OrgAdmin, db: Db, crypto: CryptoDep, settings: SettingsDep
) -> GitlabBot:
    _require_gitlab(ctx)
    try:
        me = await _with_admin(body.token, settings, lambda a: a.current_user())
    except PlatformError as exc:
        if exc.status_code in (401, 403):
            raise api_error(400, "invalid_token", "GitLab rejected this token") from exc
        raise _provider_error(exc, "validating the token") from exc
    inst = await _installation(db, ctx)
    if inst is None:
        inst = Installation(org_id=ctx.org.id, provider="gitlab")
        db.add(inst)
    inst.gitlab_bot_token_enc = crypto.encrypt(body.token)
    inst.gitlab_bot_user_id = int(me["id"])
    inst.gitlab_bot_username = str(me["username"])
    inst.status = "active"
    await db.flush()
    audit(
        db,
        ctx.org.id,
        "installation.gitlab_bot_connected",
        actor=ctx.user,
        target_type="installation",
        target_id=inst.id,
        details={"bot_username": inst.gitlab_bot_username},
    )
    await db.commit()
    return _bot(inst)


async def _attached(db: Db, inst: Installation) -> list[Repository]:
    stmt = select(Repository).where(Repository.installation_id == inst.id)
    return list((await db.execute(stmt)).scalars().all())


@router.delete("/api/orgs/{org_slug}/gitlab/bot", status_code=204)
async def delete_bot(ctx: OrgAdmin, db: Db, crypto: CryptoDep, settings: SettingsDep) -> Response:
    _require_gitlab(ctx)
    inst = await _installation(db, ctx)
    if inst is not None and inst.gitlab_bot_token_enc:
        existing = {r.provider_repo_id: snapshot(r) for r in await _attached(db, inst)}
        try:
            token = crypto.decrypt(inst.gitlab_bot_token_enc)
            plan = await _with_admin(
                token,
                settings,
                lambda a: install_hooks(a, crypto, settings.gitlab_hook_url, existing, []),
            )
        except DecryptionError:  # key rotated: can't remove hooks, just detach the repos
            plan = GitLabSyncPlan(detach=list(existing.values()))

        def _tx(s: Session) -> None:
            apply_gitlab_sync(s, inst, plan)

        await db.run_sync(_tx)
        inst.gitlab_bot_token_enc = None
        inst.status = "revoked"
        audit(
            db,
            ctx.org.id,
            "installation.gitlab_bot_removed",
            actor=ctx.user,
            target_type="installation",
            target_id=inst.id,
        )
        await db.commit()
    return Response(status_code=204)


async def _bot_token(db: Db, ctx: OrgContext, crypto: Crypto) -> tuple[str, Installation]:
    _require_gitlab(ctx)
    inst = await _installation(db, ctx)
    if inst is None or not inst.gitlab_bot_token_enc or inst.status != "active":
        raise api_error(409, "not_installed", "Connect a GitLab bot token first")
    try:
        return crypto.decrypt(inst.gitlab_bot_token_enc), inst
    except DecryptionError as exc:
        raise api_error(409, "not_installed", "Reconnect the GitLab bot token") from exc


@router.get("/api/orgs/{org_slug}/gitlab/projects", response_model=GitlabProjectList)
async def get_projects(
    ctx: OrgAdmin, db: Db, crypto: CryptoDep, settings: SettingsDep
) -> GitlabProjectList:
    token, inst = await _bot_token(db, ctx, crypto)
    try:
        projects = await _with_admin(token, settings, lambda a: list_org_projects(a, ctx.org))
    except PlatformError as exc:
        raise _provider_error(exc, "listing projects") from exc
    selected = {r.provider_repo_id for r in await _attached(db, inst)}
    return GitlabProjectList(
        whole_group=inst.gitlab_whole_group,
        projects=[
            GitlabProject(
                id=int(p["id"]),
                path_with_namespace=str(p["path_with_namespace"]),
                selected=str(p["id"]) in selected,
            )
            for p in projects
        ],
    )


@router.put("/api/orgs/{org_slug}/gitlab/projects", response_model=RepoList)
async def put_projects(
    body: GitlabProjectsRequest, ctx: OrgAdmin, db: Db, crypto: CryptoDep, settings: SettingsDep
) -> RepoList:
    token, inst = await _bot_token(db, ctx, crypto)
    existing = {r.provider_repo_id: snapshot(r) for r in await _attached(db, inst)}
    claimed = set((await db.execute(claimed_elsewhere_stmt(inst.id))).scalars())
    hook_url = settings.gitlab_hook_url

    def run(admin: GitLabAdmin) -> GitLabSyncPlan:
        projects = list_org_projects(admin, ctx.org)
        wanted = {int(p["id"]) for p in projects} if body.whole_group else set(body.project_ids)
        selected = [p for p in projects if int(p["id"]) in wanted]
        return install_hooks(admin, crypto, hook_url, existing, selected, claimed)

    try:
        plan = await _with_admin(token, settings, run)
    except PlatformError as exc:
        raise _provider_error(exc, "installing project webhooks") from exc

    def _tx(s: Session) -> None:
        apply_gitlab_sync(s, inst, plan)

    await db.run_sync(_tx)
    inst.gitlab_whole_group = body.whole_group
    audit(
        db,
        ctx.org.id,
        "installation.gitlab_projects_updated",
        actor=ctx.user,
        target_type="installation",
        target_id=inst.id,
        details={"whole_group": body.whole_group, "project_ids": list(body.project_ids)},
    )
    await db.commit()
    return RepoList(repos=await list_repos(db, ctx.org), can_install=True, install_url=None)
