"""FastAPI dependencies reading the shared clients created in `create_app` (app.state)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, cast

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.platform import is_platform_owner
from app.auth.provider_clients import GitHubUserClient, GitLabUserClient
from app.auth.sessions import SESSION_COOKIE, SessionStore
from app.auth.tokens import UserTokens
from app.crypto import Crypto
from app.errors import api_error
from app.models import Membership, Organization, User
from app.settings import Settings
from app.worker.queue import TaskQueue


def get_settings_dep(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    maker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with maker() as session:
        yield session


def get_redis(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


def get_http(request: Request) -> httpx.AsyncClient:
    return cast(httpx.AsyncClient, request.app.state.http)


def get_crypto(request: Request) -> Crypto:
    return cast(Crypto, request.app.state.crypto)


def get_queue(request: Request) -> TaskQueue:
    return cast(TaskQueue, request.app.state.queue)


def get_sessions(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


def get_github_user_client(request: Request) -> GitHubUserClient:
    return GitHubUserClient(get_settings_dep(request), get_http(request))


def get_gitlab_user_client(request: Request) -> GitLabUserClient:
    return GitLabUserClient(get_settings_dep(request), get_http(request))


Db = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
CryptoDep = Annotated[Crypto, Depends(get_crypto)]
Sessions = Annotated[SessionStore, Depends(get_sessions)]
GitHubUsers = Annotated[GitHubUserClient, Depends(get_github_user_client)]
GitLabUsers = Annotated[GitLabUserClient, Depends(get_gitlab_user_client)]


# --- current user ---------------------------------------------------------------------------


async def optional_user(request: Request, db: Db) -> User | None:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    user_id = await get_sessions(request).user_id(sid)
    if user_id is None:
        return None
    return await db.get(User, user_id)


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise api_error(401, "unauthenticated", "Sign in required")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def get_user_tokens(db: Db, crypto: CryptoDep, gh: GitHubUsers, gl: GitLabUsers) -> UserTokens:
    return UserTokens(db, crypto, gh, gl)


Tokens = Annotated[UserTokens, Depends(get_user_tokens)]


# --- organization context & roles (spec §6.2) -----------------------------------------------


@dataclass
class OrgContext:
    user: User
    org: Organization
    role: str


async def get_org_context(org_slug: str, user: CurrentUser, db: Db) -> OrgContext:
    """The org addressed by ``org_slug`` if the user is a member; 404 otherwise (no leak)."""
    row = (
        await db.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Organization.slug == org_slug, Membership.user_id == user.id)
        )
    ).first()
    if row is None:
        raise api_error(404, "not_found", "Organization not found")
    return OrgContext(user=user, org=row[0], role=row[1])


def require_role(*roles: str) -> Callable[..., Awaitable[OrgContext]]:
    async def dep(ctx: Annotated[OrgContext, Depends(get_org_context)]) -> OrgContext:
        if ctx.role not in roles:
            raise api_error(403, "forbidden", "Your role does not allow this action")
        return ctx

    return dep


OrgMember = Annotated[OrgContext, Depends(get_org_context)]


async def viewer_is_platform_owner(user: CurrentUser, db: Db, settings: SettingsDep) -> bool:
    """True only for ``PLATFORM_OWNERS``: they may see internal LLM cost / tokens / models."""
    return await is_platform_owner(db, settings, user)


PlatformOwner = Annotated[bool, Depends(viewer_is_platform_owner)]
OrgAdmin = Annotated[OrgContext, Depends(require_role("admin"))]
OrgBilling = Annotated[OrgContext, Depends(require_role("admin", "billing_admin"))]
