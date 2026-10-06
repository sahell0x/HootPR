"""GitPlatform instances acting as the signed-in user (Change Stack submit review / merge).

Built from the user's own OAuth token (GitHub App user-to-server token, GitLab OAuth token), so
the provider attributes the review / merge to the human and applies their permissions. These
instances must never be used for bot work (no clone credentials, no bot-comment editing).
"""

from __future__ import annotations

from app.platforms.base import CloneCredentials, GitPlatform, ProviderName, RepoRef
from app.platforms.github.app_auth import GITHUB_HEADERS
from app.platforms.github.platform import GitHubPlatform
from app.platforms.gitlab.platform import GitLabPlatform
from app.platforms.http import HttpClient
from app.settings import Settings


class UserTokenOnly(Exception):
    """A bot-only operation was attempted on a user-token platform."""


class GitHubUserPlatform(GitHubPlatform):
    def __init__(self, token: str, *, api_url: str, web_url: str) -> None:
        # Deliberately not calling super().__init__: there is no App installation here.
        self._bot_login = ""
        self._iid = 0
        self._http = HttpClient(api_url, {**GITHUB_HEADERS, "Authorization": f"Bearer {token}"})
        self._web = web_url.rstrip("/")
        self._thread_cache = {}

    def clone_credentials(self, repo: RepoRef) -> CloneCredentials:
        raise UserTokenOnly("clone credentials are bot-only")


class GitLabUserPlatform(GitLabPlatform):
    def __init__(self, token: str, *, base_url: str) -> None:
        super().__init__(token, base_url=base_url, bot_user_id=-1)
        # OAuth tokens authenticate with a Bearer header (PRIVATE-TOKEN is for PATs).
        self._http.close()
        self._http = HttpClient(
            f"{base_url.rstrip('/')}/api/v4",
            {"Authorization": f"Bearer {token}", "User-Agent": "HootPR"},
        )

    def clone_credentials(self, repo: RepoRef) -> CloneCredentials:
        raise UserTokenOnly("clone credentials are bot-only")


def user_platform(provider: ProviderName | str, token: str, settings: Settings) -> GitPlatform:
    if provider == "github":
        return GitHubUserPlatform(
            token, api_url=settings.github_api_url, web_url=settings.github_web_url
        )
    return GitLabUserPlatform(token, base_url=settings.gitlab_base_url)
