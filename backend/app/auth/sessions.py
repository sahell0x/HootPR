"""Redis-backed sessions (spec §5, last line) and auth cookies (plan: API contract).

The cookie carries a random 256-bit id; Redis stores ``session:<HMAC-SHA256(secret, id)>`` →
user id with a 14-day sliding TTL, so a Redis dump never contains usable session ids.
"""

import hashlib
import hmac
import secrets
from uuid import UUID

from redis.asyncio import Redis
from starlette.responses import Response

from app.settings import Settings

SESSION_COOKIE = "hootpr_session"
CSRF_COOKIE = "hootpr_csrf"
SESSION_TTL_S = 14 * 24 * 3600


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class SessionStore:
    def __init__(self, redis: Redis, secret: bytes, ttl_s: int = SESSION_TTL_S) -> None:
        self._r = redis
        self._secret = secret
        self._ttl = ttl_s

    def _key(self, sid: str) -> str:
        return "session:" + hmac.new(self._secret, sid.encode(), hashlib.sha256).hexdigest()

    async def create(self, user_id: UUID) -> str:
        sid = secrets.token_urlsafe(32)
        await self._r.set(self._key(sid), str(user_id), ex=self._ttl)
        return sid

    async def user_id(self, sid: str) -> UUID | None:
        value = await self._r.getex(self._key(sid), ex=self._ttl)
        if not value:
            return None
        raw = value.decode() if isinstance(value, bytes) else str(value)
        try:
            return UUID(raw)
        except ValueError:
            return None

    async def destroy(self, sid: str) -> None:
        await self._r.delete(self._key(sid))


def _domain(settings: Settings) -> str | None:
    return settings.cookie_domain or None


def set_csrf_cookie(response: Response, settings: Settings, csrf: str) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=SESSION_TTL_S,
        httponly=False,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        path="/",
        domain=_domain(settings),
    )


def set_auth_cookies(response: Response, settings: Settings, sid: str, csrf: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=SESSION_TTL_S,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        path="/",
        domain=_domain(settings),
    )
    set_csrf_cookie(response, settings, csrf)


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(
            name,
            path="/",
            domain=_domain(settings),
            httponly=httponly,
            samesite=settings.cookie_samesite,
            secure=settings.cookie_secure,
        )
