"""GitHub App "Setup URL" (`{APP_BASE_URL}/api/github/setup`, decision P8, spec §6.3).

GitHub redirects here after install/update with ``installation_id``. The signed-in user's
membership in the installation's account is verified with *their* token, the org + installation
rows are created and a repository sync is queued. The ``installation.created`` webhook does the
same work independently, so whichever arrives first wins and the other is a no-op upsert.
"""

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.analytics.audit import audit
from app.auth.provider_clients import OAuthError, ReauthRequired
from app.billing.ledger import CreditLedger
from app.deps import Db, GitHubUsers, OptionalUser, SettingsDep, Tokens, get_queue
from app.kv import RedisKV
from app.logging import get_logger
from app.models import Identity, Organization
from app.orgs.installations import upsert_github_installation
from app.orgs.service import ensure_organization, upsert_membership
from app.platforms.base import PlatformError
from app.platforms.github.app_auth import make_github_app_auth

router = APIRouter(tags=["github"])
log = get_logger(__name__)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302)


@router.get("/api/github/setup")
async def github_setup(
    request: Request,
    user: OptionalUser,
    db: Db,
    settings: SettingsDep,
    tokens: Tokens,
    gh: GitHubUsers,
    installation_id: int | None = None,
    setup_action: str | None = None,
) -> RedirectResponse:
    base = settings.app_base_url.rstrip("/")
    if installation_id is None:  # e.g. setup_action=request (an org owner must approve)
        if user is None:
            return _redirect(f"{base}/login")
        return _redirect(f"{base}/orgs")
    if user is None:
        nxt = quote(f"/api/github/setup?installation_id={installation_id}", safe="")
        return _redirect(f"{base}/login?next={nxt}")
    ident = (
        await db.execute(
            select(Identity).where(Identity.user_id == user.id, Identity.provider == "github")
        )
    ).scalar_one_or_none()
    if ident is None:
        return _redirect(f"{base}/orgs?error=github_identity_required")

    app_auth = make_github_app_auth(settings, RedisKV(request.app.state.sync_redis))
    try:
        inst = await run_in_threadpool(app_auth.get_installation, installation_id)
    except PlatformError as exc:
        log.warning("github_setup_installation_lookup_failed", error=str(exc))
        return _redirect(f"{base}/orgs?error=installation_not_found")
    acc = inst["account"]
    account_id = str(acc["id"])
    login = str(acc["login"])
    if account_id == ident.provider_user_id:
        role, kind = "admin", "personal"
    else:
        try:
            role_hint = await tokens.call(ident, lambda t: gh.org_role(t, account_id))
        except ReauthRequired:
            nxt = quote(f"/api/github/setup?installation_id={installation_id}", safe="")
            return _redirect(f"{base}/login?error=oauth_failed&next={nxt}")
        except OAuthError:
            return _redirect(f"{base}/orgs?error=provider_error")
        if role_hint is None:
            return _redirect(f"{base}/orgs?error=not_a_member")
        role, kind = role_hint, "org"

    def _tx(s: Session) -> Organization:
        org, _ = ensure_organization(
            s,
            CreditLedger(),
            settings,
            provider="github",
            provider_org_id=account_id,
            kind=kind,
            name=login,
            path=login,
            avatar_url=acc.get("avatar_url"),
        )
        upsert_membership(s, user.id, org.id, role)
        upsert_github_installation(s, org.id, installation_id)
        return org

    org = await db.run_sync(_tx)
    audit(
        db,
        org.id,
        "installation.github_installed",
        actor=user,
        target_type="installation",
        target_id=str(installation_id),
        details={"account": login},
    )
    await db.commit()
    get_queue(request).enqueue("installations.sync_github", installation_id)
    return _redirect(f"{base}/o/{org.slug}/repos")
