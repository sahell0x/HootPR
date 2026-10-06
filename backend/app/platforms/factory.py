"""Build the right GitPlatform for a repository row (worker side)."""

from collections.abc import Callable
from typing import cast

from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.kv import KV
from app.models import Installation, Repository
from app.platforms.base import GitPlatform, ProviderName, RepoRef
from app.platforms.github.app_auth import make_github_app_auth
from app.platforms.github.platform import GitHubPlatform
from app.platforms.gitlab.platform import GitLabPlatform
from app.settings import Settings

PlatformFactory = Callable[[Session, Repository], GitPlatform]


class NotInstalled(Exception):
    """The repository has no active installation / bot token."""


def repo_ref(repo: Repository) -> RepoRef:
    return RepoRef(cast(ProviderName, repo.provider), repo.provider_repo_id, repo.full_name)


def make_platform_factory(settings: Settings, kv: KV, crypto: Crypto) -> PlatformFactory:
    def build(s: Session, repo: Repository) -> GitPlatform:
        inst = s.get(Installation, repo.installation_id) if repo.installation_id else None
        if inst is None or inst.status != "active":
            raise NotInstalled(repo.full_name)
        if repo.provider == "github":
            if inst.github_installation_id is None:
                raise NotInstalled(repo.full_name)
            return GitHubPlatform(
                make_github_app_auth(settings, kv),
                inst.github_installation_id,
                web_url=settings.github_web_url,
                bot_login=f"{settings.github_app_slug}[bot]",
            )
        if not inst.gitlab_bot_token_enc:
            raise NotInstalled(repo.full_name)
        return GitLabPlatform(
            crypto.decrypt(inst.gitlab_bot_token_enc),
            base_url=settings.gitlab_base_url,
            bot_user_id=inst.gitlab_bot_user_id,
        )

    return build


def close_platform(platform: GitPlatform) -> None:
    """Release the platform's HTTP client, if it has one (LocalPlatform does not)."""
    close = getattr(platform, "close", None)
    if callable(close):
        close()
