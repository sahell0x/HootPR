"""User-token calls to GitHub/GitLab for sign-in and org discovery (spec §6.1, §6.2)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.settings import Settings


class OAuthError(Exception):
    """The provider rejected the OAuth exchange or returned an unexpected error."""


class ReauthRequired(Exception):
    """The stored user token is expired/revoked (provider answered 401)."""


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    provider_user_id: str
    username: str
    display_name: str
    email: str | None
    avatar_url: str | None


@dataclass(frozen=True)
class OrgCandidateData:
    provider: str
    provider_org_id: str
    kind: str  # org | group | personal
    name: str
    path: str  # GitHub login / GitLab full_path (used for the slug)
    avatar_url: str | None
    installed: bool
    role_hint: str | None


def _tokens(data: Any) -> TokenSet:
    if not isinstance(data, dict) or "access_token" not in data:
        err = data.get("error_description") or data.get("error") if isinstance(data, dict) else ""
        raise OAuthError(str(err or "no access token in response"))
    expires = data.get("expires_in")
    return TokenSet(
        str(data["access_token"]),
        str(data["refresh_token"]) if data.get("refresh_token") else None,
        datetime.now(UTC) + timedelta(seconds=int(expires)) if expires else None,
    )


async def _get(
    http: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> Any:
    """GET JSON. 401 → ReauthRequired, 404 → None, other errors → OAuthError."""
    try:
        resp = await http.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise OAuthError(f"GET {url}: {type(exc).__name__}") from exc
    if resp.status_code == 401:
        raise ReauthRequired(url)
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise OAuthError(f"GET {url}: HTTP {resp.status_code}")
    return resp.json()


async def _post_token(http: httpx.AsyncClient, url: str, data: dict[str, str]) -> TokenSet:
    try:
        resp = await http.post(url, headers={"Accept": "application/json"}, data=data)
    except httpx.HTTPError as exc:
        raise OAuthError(f"token exchange failed: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        raise OAuthError(f"token exchange failed: HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise OAuthError("token exchange returned non-JSON") from exc
    return _tokens(payload)


def _gh_role(membership: dict[str, Any]) -> str:
    return "admin" if membership.get("role") == "admin" else "member"


class GitHubUserClient:
    """Calls made with a GitHub App user-to-server token."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self._api = settings.github_api_url.rstrip("/")
        self._web = settings.github_web_url.rstrip("/")

    @staticmethod
    def _h(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def enabled(self) -> bool:
        return bool(self._s.github_oauth_client_id)

    def redirect_uri(self) -> str:
        return f"{self._s.api_base_url.rstrip('/')}/api/auth/github/callback"

    def authorize_url(self, state: str) -> str:
        q = urlencode(
            {
                "client_id": self._s.github_oauth_client_id,
                "redirect_uri": self.redirect_uri(),
                "state": state,
            }
        )
        return f"{self._web}/login/oauth/authorize?{q}"

    async def exchange_code(self, code: str) -> TokenSet:
        return await _post_token(
            self._http,
            f"{self._web}/login/oauth/access_token",
            {
                "client_id": self._s.github_oauth_client_id,
                "client_secret": self._s.github_oauth_client_secret.get_secret_value(),
                "code": code,
                "redirect_uri": self.redirect_uri(),
            },
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        """GitHub App user tokens expire after 8 h; exchange the refresh token for a new pair."""
        return await _post_token(
            self._http,
            f"{self._web}/login/oauth/access_token",
            {
                "client_id": self._s.github_oauth_client_id,
                "client_secret": self._s.github_oauth_client_secret.get_secret_value(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    async def profile(self, token: str) -> ProviderProfile:
        u = await _get(self._http, f"{self._api}/user", self._h(token))
        if not u:
            raise OAuthError("GitHub /user returned nothing")
        try:
            emails = await _get(self._http, f"{self._api}/user/emails", self._h(token)) or []
        except OAuthError:  # the App may lack the "email addresses" permission
            emails = []
        primary = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
        return ProviderProfile(
            "github",
            str(u["id"]),
            str(u["login"]),
            str(u.get("name") or u["login"]),
            primary or u.get("email"),
            u.get("avatar_url"),
        )

    async def _memberships(self, token: str) -> list[dict[str, Any]]:
        data = await _get(
            self._http,
            f"{self._api}/user/memberships/orgs",
            self._h(token),
            {"state": "active", "per_page": 100},
        )
        return list(data or [])

    async def candidates(self, token: str) -> list[OrgCandidateData]:
        u = await _get(self._http, f"{self._api}/user", self._h(token))
        if not u:
            raise OAuthError("GitHub /user returned nothing")
        inst = await _get(
            self._http, f"{self._api}/user/installations", self._h(token), {"per_page": 100}
        ) or {"installations": []}
        installed = {str(i["account"]["id"]): i["account"] for i in inst.get("installations", [])}
        uid = str(u["id"])
        out = [
            OrgCandidateData(
                "github",
                uid,
                "personal",
                str(u["login"]),
                str(u["login"]),
                u.get("avatar_url"),
                uid in installed,
                "admin",
            )
        ]
        seen = {uid}
        for m in await self._memberships(token):
            o = m["organization"]
            oid = str(o["id"])
            seen.add(oid)
            out.append(
                OrgCandidateData(
                    "github",
                    oid,
                    "org",
                    str(o["login"]),
                    str(o["login"]),
                    o.get("avatar_url"),
                    oid in installed,
                    _gh_role(m),
                )
            )
        for oid, acc in installed.items():
            if oid not in seen:
                out.append(
                    OrgCandidateData(
                        "github",
                        oid,
                        "org",
                        str(acc["login"]),
                        str(acc["login"]),
                        acc.get("avatar_url"),
                        True,
                        None,
                    )
                )
        return out

    async def org_role(self, token: str, org_id: str) -> str | None:
        for m in await self._memberships(token):
            if str(m["organization"]["id"]) == org_id:
                return _gh_role(m)
        return None

    async def org_by_id(self, token: str, org_id: str) -> dict[str, Any] | None:
        found = await self.org_membership(token, org_id)
        return found[0] if found else None

    async def org_membership(self, token: str, org_id: str) -> tuple[dict[str, Any], str] | None:
        """(organization json, role) when the user is an active member of ``org_id``."""
        for m in await self._memberships(token):
            if str(m["organization"]["id"]) == org_id:
                org: dict[str, Any] = m["organization"]
                return org, _gh_role(m)
        return None


class GitLabUserClient:
    """Calls made with a GitLab OAuth user token (scopes ``read_user read_api``)."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self._base = settings.gitlab_base_url.rstrip("/")

    @staticmethod
    def _h(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @property
    def enabled(self) -> bool:
        return bool(self._s.gitlab_oauth_client_id)

    def redirect_uri(self) -> str:
        return f"{self._s.api_base_url.rstrip('/')}/api/auth/gitlab/callback"

    def authorize_url(self, state: str, challenge: str) -> str:
        q = urlencode(
            {
                "client_id": self._s.gitlab_oauth_client_id,
                "redirect_uri": self.redirect_uri(),
                "response_type": "code",
                "state": state,
                "scope": "read_user read_api",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self._base}/oauth/authorize?{q}"

    async def exchange_code(self, code: str, verifier: str) -> TokenSet:
        return await _post_token(
            self._http,
            f"{self._base}/oauth/token",
            {
                "client_id": self._s.gitlab_oauth_client_id,
                "client_secret": self._s.gitlab_oauth_client_secret.get_secret_value(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri(),
                "code_verifier": verifier,
            },
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        """GitLab OAuth access tokens expire after 2 h; use the refresh token."""
        return await _post_token(
            self._http,
            f"{self._base}/oauth/token",
            {
                "client_id": self._s.gitlab_oauth_client_id,
                "client_secret": self._s.gitlab_oauth_client_secret.get_secret_value(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": self.redirect_uri(),
            },
        )

    async def profile(self, token: str) -> ProviderProfile:
        u = await _get(self._http, f"{self._base}/api/v4/user", self._h(token))
        if not u:
            raise OAuthError("GitLab /user returned nothing")
        return ProviderProfile(
            "gitlab",
            str(u["id"]),
            str(u["username"]),
            str(u.get("name") or u["username"]),
            u.get("email") or u.get("public_email") or None,
            u.get("avatar_url"),
        )

    async def candidates(self, token: str, user_id: str) -> list[OrgCandidateData]:
        u = await _get(self._http, f"{self._base}/api/v4/user", self._h(token))
        if not u:
            raise OAuthError("GitLab /user returned nothing")
        out = [
            OrgCandidateData(
                "gitlab",
                f"user:{user_id}",
                "personal",
                str(u["username"]),
                str(u["username"]),
                u.get("avatar_url"),
                False,
                "admin",
            )
        ]
        groups = (
            await _get(
                self._http,
                f"{self._base}/api/v4/groups",
                self._h(token),
                {"min_access_level": 40, "per_page": 100},
            )
            or []
        )
        for g in groups:
            out.append(
                OrgCandidateData(
                    "gitlab",
                    str(g["id"]),
                    "group",
                    str(g.get("full_name") or g["name"]),
                    str(g["full_path"]),
                    g.get("avatar_url"),
                    False,
                    None,
                )
            )
        return out

    async def group(self, token: str, group_id: str) -> dict[str, Any] | None:
        data: dict[str, Any] | None = await _get(
            self._http, f"{self._base}/api/v4/groups/{group_id}", self._h(token)
        )
        return data

    async def group_role(self, token: str, group_id: str, user_id: str) -> str | None:
        """Owner (50) → admin; Maintainer (40) and below → member; not a member → None."""
        m = await _get(
            self._http,
            f"{self._base}/api/v4/groups/{group_id}/members/all/{user_id}",
            self._h(token),
        )
        if not m:
            return None
        return "admin" if int(m.get("access_level", 0)) >= 50 else "member"
