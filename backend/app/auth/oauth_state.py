"""OAuth ``state`` (10-minute, single use, in Redis), safe post-login redirects and PKCE."""

import base64
import hashlib
import hmac
import secrets
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis

STATE_TTL_S = 600
DEFAULT_NEXT = "/orgs"
# Short-lived HttpOnly cookie binding a ``state`` to the browser that started the flow.
NONCE_COOKIE = "hootpr_oauth"
NONCE_COOKIE_PATH = "/api/auth"


class OAuthState(BaseModel):
    provider: Literal["github", "gitlab"]
    next: str = DEFAULT_NEXT
    link_user_id: str | None = None
    code_verifier: str | None = None
    nonce: str = ""


def new_nonce() -> str:
    return secrets.token_urlsafe(32)


def nonce_matches(state: OAuthState, cookie: str | None) -> bool:
    """Constant-time check that the callback runs in the browser that called ``/login``."""
    if not state.nonce or not cookie:
        return False
    return hmac.compare_digest(state.nonce.encode(), cookie.encode())


def safe_next(path: str | None) -> str:
    """Only same-site absolute paths are allowed as post-login destinations (no open redirect)."""
    if (
        not path
        or not path.startswith("/")
        or path.startswith("//")
        or path.startswith("/\\")
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path)
    ):
        return DEFAULT_NEXT
    return path


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class OAuthStateStore:
    def __init__(self, redis: Redis) -> None:
        self._r = redis

    async def put(self, state: OAuthState) -> str:
        token = secrets.token_urlsafe(32)
        await self._r.set(f"oauth_state:{token}", state.model_dump_json(), ex=STATE_TTL_S)
        return token

    async def pop(self, token: str) -> OAuthState | None:
        raw = await self._r.getdel(f"oauth_state:{token}")
        if not raw:
            return None
        return OAuthState.model_validate_json(raw)
