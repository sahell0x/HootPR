"""Auth routes: current user, logout (Task 15) and OAuth sign-in / linking (Task 16)."""

from typing import Annotated, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.schemas import CsrfToken, Identity, Me, Provider
from app.auth.oauth_state import (
    NONCE_COOKIE,
    NONCE_COOKIE_PATH,
    STATE_TTL_S,
    OAuthState,
    OAuthStateStore,
    new_nonce,
    nonce_matches,
    pkce_pair,
    safe_next,
)
from app.auth.provider_clients import OAuthError, ReauthRequired
from app.auth.service import IdentityInUse, upsert_identity
from app.auth.sessions import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    clear_auth_cookies,
    new_csrf_token,
    set_auth_cookies,
    set_csrf_cookie,
)
from app.deps import (
    CryptoDep,
    CurrentUser,
    Db,
    GitHubUsers,
    GitLabUsers,
    OptionalUser,
    Sessions,
    SettingsDep,
    get_redis,
)
from app.logging import get_logger
from app.models import Identity as IdentityRow
from app.settings import Settings

router = APIRouter(tags=["auth"])
log = get_logger(__name__)


@router.get("/api/me", response_model=Me)
async def me(
    request: Request, response: Response, user: CurrentUser, db: Db, settings: SettingsDep
) -> Me:
    rows = (
        (
            await db.execute(
                select(IdentityRow)
                .where(IdentityRow.user_id == user.id)
                .order_by(IdentityRow.created_at)
            )
        )
        .scalars()
        .all()
    )
    csrf = request.cookies.get(CSRF_COOKIE)
    if not csrf:
        csrf = new_csrf_token()
        set_csrf_cookie(response, settings, csrf)
    return Me(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        csrf_token=csrf,
        identities=[
            Identity(
                provider=cast(Provider, r.provider),
                provider_user_id=r.provider_user_id,
                username=r.username,
            )
            for r in rows
        ],
    )


@router.get("/api/auth/csrf", response_model=CsrfToken)
async def csrf_token(request: Request, response: Response, settings: SettingsDep) -> CsrfToken:
    """The double-submit CSRF token in the body (the dashboard is a separate origin and cannot
    read the API's cookie); sets the cookie when missing. Mutations echo it in X-CSRF-Token."""
    csrf = request.cookies.get(CSRF_COOKIE)
    if not csrf:
        csrf = new_csrf_token()
        set_csrf_cookie(response, settings, csrf)
    response.headers["Cache-Control"] = "no-store"
    return CsrfToken(csrf_token=csrf)


@router.post("/api/auth/logout", status_code=204)
async def logout(request: Request, sessions: Sessions, settings: SettingsDep) -> Response:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await sessions.destroy(sid)
    resp = Response(status_code=204)
    clear_auth_cookies(resp, settings)
    return resp


# --- OAuth sign-in and account linking (spec §6.1) ------------------------------------------


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302)


def post_login_url(settings: Settings, next_path: str) -> str:
    """Dashboard pages live on APP_BASE_URL; a ``/api/...`` resume target (the GitHub App setup
    redirect) lives on API_BASE_URL."""
    base = settings.api_base_url if next_path.startswith("/api/") else settings.app_base_url
    return f"{base.rstrip('/')}{next_path}"


@router.get("/api/auth/{provider}/login")
async def oauth_login(
    provider: Provider,
    request: Request,
    user: OptionalUser,
    gh: GitHubUsers,
    gl: GitLabUsers,
    settings: SettingsDep,
    next_: Annotated[str | None, Query(alias="next")] = None,
) -> RedirectResponse:
    """Start OAuth. With an existing session this links the identity to the signed-in user.

    The ``state`` is bound to this browser by a random nonce kept in a short-lived HttpOnly
    cookie; the callback refuses a state whose nonce does not match (login CSRF / identity
    hijack via a forwarded authorize URL).
    """
    if not (gh.enabled if provider == "github" else gl.enabled):
        return _redirect(f"{settings.app_base_url.rstrip('/')}/login?error=provider_not_configured")
    verifier, challenge = pkce_pair() if provider == "gitlab" else (None, "")
    nonce = new_nonce()
    token = await OAuthStateStore(get_redis(request)).put(
        OAuthState(
            provider=provider,
            next=safe_next(next_),
            link_user_id=str(user.id) if user else None,
            code_verifier=verifier,
            nonce=nonce,
        )
    )
    url = gh.authorize_url(token) if provider == "github" else gl.authorize_url(token, challenge)
    resp = _redirect(url)
    resp.set_cookie(
        NONCE_COOKIE,
        nonce,
        max_age=STATE_TTL_S,
        httponly=True,
        samesite="lax",  # sent on the provider's top-level GET redirect back to us
        secure=settings.cookie_secure,
        path=NONCE_COOKIE_PATH,
    )
    return resp


def _clear_nonce(resp: RedirectResponse, settings: Settings) -> RedirectResponse:
    resp.delete_cookie(
        NONCE_COOKIE,
        path=NONCE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return resp


@router.get("/api/auth/{provider}/callback")
async def oauth_callback(
    provider: Provider,
    request: Request,
    db: Db,
    settings: SettingsDep,
    crypto: CryptoDep,
    gh: GitHubUsers,
    gl: GitLabUsers,
    sessions: Sessions,
    current: OptionalUser,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    fail = f"{settings.app_base_url.rstrip('/')}/login?error="

    def failed(reason: str) -> RedirectResponse:
        return _clear_nonce(_redirect(fail + reason), settings)

    st = await OAuthStateStore(get_redis(request)).pop(state) if state else None
    if (
        st is None
        or st.provider != provider
        or not nonce_matches(st, request.cookies.get(NONCE_COOKIE))
    ):
        return failed("oauth_state_invalid")
    # Linking only ever attaches to the user whose session started the flow.
    if st.link_user_id is not None and (current is None or str(current.id) != st.link_user_id):
        return failed("oauth_state_invalid")
    if error or not code:
        return failed("oauth_failed")
    try:
        if provider == "github":
            tokens = await gh.exchange_code(code)
            profile = await gh.profile(tokens.access_token)
        else:
            tokens = await gl.exchange_code(code, st.code_verifier or "")
            profile = await gl.profile(tokens.access_token)
    except (OAuthError, ReauthRequired, httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("oauth_failed", provider=provider, error=type(exc).__name__)
        return failed("oauth_failed")
    link = UUID(st.link_user_id) if st.link_user_id else None
    try:
        user = await db.run_sync(lambda s: upsert_identity(s, crypto, profile, tokens, link))
        await db.commit()
    except IdentityInUse:
        await db.rollback()
        return failed("identity_in_use")
    except IntegrityError:  # concurrent first sign-in with the same identity
        await db.rollback()
        return failed("oauth_failed")
    old_sid = request.cookies.get(SESSION_COOKIE)
    if old_sid:  # rotate the session id on every sign-in (session fixation)
        await sessions.destroy(old_sid)
    sid = await sessions.create(user.id)
    resp = _redirect(post_login_url(settings, st.next))
    set_auth_cookies(resp, settings, sid, new_csrf_token())
    return _clear_nonce(resp, settings)
