"""GitHub App authentication: app JWT + installation tokens cached in Redis (spec §4.1)."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Any

import httpx
import jwt

from app.kv import KV
from app.platforms.http import HttpClient
from app.settings import Settings

GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "HootPR",
}
TOKEN_SAFETY_MARGIN_S = 300


class _InstallationAuth(httpx.Auth):
    """Adds a (cached) installation token to every request."""

    def __init__(self, app_auth: GitHubAppAuth, installation_id: int) -> None:
        self._app_auth = app_auth
        self._iid = installation_id

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        token = self._app_auth.installation_token(self._iid)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


class GitHubAppAuth:
    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        kv: KV,
        api_url: str,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._app_id = app_id
        self._key = private_key_pem
        self._kv = kv
        self.api_url = api_url.rstrip("/")
        self._clock = clock

    def app_jwt(self) -> str:
        # iat backdated 60 s for clock drift; total lifetime stays under GitHub's 10 min cap.
        now = int(self._clock())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self._app_id}, self._key, algorithm="RS256"
        )

    def _app_client(self) -> HttpClient:
        return HttpClient(
            self.api_url, {**GITHUB_HEADERS, "Authorization": f"Bearer {self.app_jwt()}"}
        )

    def installation_token(self, installation_id: int) -> str:
        key = f"gh:insttoken:{installation_id}"
        cached = self._kv.get(key)
        if cached:
            return cached
        client = self._app_client()
        try:
            data = client.request(
                "POST", f"/app/installations/{installation_id}/access_tokens"
            ).json()
        finally:
            client.close()
        token = str(data["token"])
        expires = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
        ttl = int(expires.timestamp() - self._clock() - TOKEN_SAFETY_MARGIN_S)
        if ttl > 0:
            self._kv.set(key, token, ex=ttl)
        return token

    def invalidate_installation_token(self, installation_id: int) -> None:
        self._kv.delete(f"gh:insttoken:{installation_id}")

    def get_installation(self, installation_id: int) -> dict[str, Any]:
        client = self._app_client()
        try:
            data: dict[str, Any] = client.get_json(f"/app/installations/{installation_id}")
            return data
        finally:
            client.close()

    def installation_client(self, installation_id: int) -> HttpClient:
        return HttpClient(
            self.api_url, GITHUB_HEADERS, auth=_InstallationAuth(self, installation_id)
        )

    def list_installation_repositories(self, installation_id: int) -> list[dict[str, Any]]:
        client = self.installation_client(installation_id)
        try:
            return list(client.paginate("/installation/repositories", item_key="repositories"))
        finally:
            client.close()


def make_github_app_auth(settings: Settings, kv: KV) -> GitHubAppAuth:
    return GitHubAppAuth(
        settings.github_app_id, settings.github_private_key(), kv, settings.github_api_url
    )
