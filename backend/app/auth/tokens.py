"""Use a stored user token, refreshing it once when it is expired or rejected.

GitHub App user-to-server tokens live 8 h, GitLab OAuth tokens 2 h. When no refresh token is
stored, or the refresh fails, ``ReauthRequired`` propagates and the API answers
``401 reauth_required`` so the dashboard sends the user through sign-in again.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider_clients import GitHubUserClient, GitLabUserClient, OAuthError, ReauthRequired
from app.crypto import Crypto, DecryptionError
from app.models import Identity

T = TypeVar("T")
EXPIRY_MARGIN = timedelta(seconds=60)


class UserTokens:
    def __init__(
        self, db: AsyncSession, crypto: Crypto, gh: GitHubUserClient, gl: GitLabUserClient
    ) -> None:
        self._db = db
        self._crypto = crypto
        self._gh = gh
        self._gl = gl

    def _decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._crypto.decrypt(value)
        except DecryptionError:
            return None

    async def _refresh(self, ident: Identity, stale_access: str | None) -> str:
        """Refresh under a row lock on the identity. Refresh tokens are single use (GitHub) or
        rotated (GitLab), so parallel requests must not spend the same one: whoever gets the
        lock second re-reads the row and reuses the token the first one stored."""
        await self._db.execute(
            select(Identity)
            .where(Identity.id == ident.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current = self._decrypt(ident.access_token_enc)
        if current and current != stale_access and not self._expired(ident):
            await self._db.commit()  # someone else refreshed while we waited; release the lock
            return current
        refresh_token = self._decrypt(ident.refresh_token_enc)
        if not refresh_token:
            raise ReauthRequired(f"{ident.provider} token expired and no refresh token")
        client = self._gh if ident.provider == "github" else self._gl
        try:
            tokens = await client.refresh(refresh_token)
        except OAuthError as exc:
            raise ReauthRequired(f"{ident.provider} token refresh failed") from exc
        ident.access_token_enc = self._crypto.encrypt(tokens.access_token)
        if tokens.refresh_token:
            ident.refresh_token_enc = self._crypto.encrypt(tokens.refresh_token)
        ident.token_expires_at = tokens.expires_at
        await self._db.commit()
        return tokens.access_token

    @staticmethod
    def _expired(ident: Identity) -> bool:
        expires = ident.token_expires_at
        return expires is not None and expires <= datetime.now(UTC) + EXPIRY_MARGIN

    async def _token(self, ident: Identity) -> tuple[str, bool]:
        """(access token, whether it was just refreshed)."""
        access = self._decrypt(ident.access_token_enc)
        if not access or self._expired(ident):
            return await self._refresh(ident, access), True
        return access, False

    async def token(self, ident: Identity) -> str:
        return (await self._token(ident))[0]

    async def call(self, ident: Identity, fn: Callable[[str], Awaitable[T]]) -> T:
        """Run ``fn(token)``; on a provider 401 refresh once (unless just refreshed) and retry."""
        token, refreshed = await self._token(ident)
        try:
            return await fn(token)
        except ReauthRequired:
            if refreshed or not ident.refresh_token_enc:
                raise
            return await fn(await self._refresh(ident, token))
