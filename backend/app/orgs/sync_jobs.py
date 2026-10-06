"""Worker-side repository sync jobs (``installations.sync_github``, ``gitlab.sync_hooks``)."""

from sqlalchemy import select

from app.logging import get_logger
from app.models import Installation, Organization, Repository
from app.orgs.gitlab_sync import (
    apply_gitlab_sync,
    claimed_elsewhere,
    install_hooks,
    list_org_projects,
    snapshot,
)
from app.orgs.installations import sync_github_repositories
from app.platforms.base import PlatformError
from app.worker.context import WorkerContext

log = get_logger(__name__)


def sync_github_installation(ctx: WorkerContext, installation_id: int) -> int:
    """Re-read the repositories a GitHub installation can access. Returns repos synced."""
    with ctx.session_factory() as s:
        inst = s.execute(
            select(Installation).where(Installation.github_installation_id == installation_id)
        ).scalar_one_or_none()
        if inst is None or inst.status != "active":
            return 0
        repos = ctx.github_repos(installation_id)
        n = len(sync_github_repositories(s, inst, repos, replace=True))
        s.commit()
        return n


def sync_gitlab_orgs(ctx: WorkerContext, org_id: str | None = None) -> int:
    """Hourly (and on demand): re-install project hooks for every GitLab org with a bot.

    Whole-group orgs pick up new projects; others keep their selection. Returns orgs synced.
    """
    done = 0
    with ctx.session_factory() as s:
        q = select(Installation).where(
            Installation.provider == "gitlab",
            Installation.status == "active",
            Installation.gitlab_bot_token_enc.is_not(None),
        )
        for inst in s.execute(q).scalars().all():
            if org_id is not None and str(inst.org_id) != org_id:
                continue
            org = s.get(Organization, inst.org_id)
            if org is None or not inst.gitlab_bot_token_enc:
                continue
            attached = (
                s.execute(select(Repository).where(Repository.installation_id == inst.id))
                .scalars()
                .all()
            )
            existing = {r.provider_repo_id: snapshot(r) for r in attached}
            claimed = claimed_elsewhere(s, inst.id)
            try:
                admin = ctx.gitlab_admin(ctx.crypto.decrypt(inst.gitlab_bot_token_enc))
                try:
                    projects = list_org_projects(admin, org)
                    selected = (
                        projects
                        if inst.gitlab_whole_group
                        else [p for p in projects if str(p["id"]) in existing]
                    )
                    plan = install_hooks(
                        admin,
                        ctx.crypto,
                        ctx.settings.gitlab_hook_url,
                        existing,
                        selected,
                        claimed,
                    )
                finally:
                    admin.close()
            except PlatformError:
                log.exception("gitlab_sync_failed", org_id=str(org.id))
                continue
            apply_gitlab_sync(s, inst, plan)
            s.commit()
            done += 1
    return done
