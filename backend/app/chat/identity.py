"""Who HootPR is on each platform (phase-3 R3/R4)."""

from dataclasses import dataclass

from app.platforms.base import ProviderName
from app.settings import Settings


@dataclass(frozen=True)
class BotIdentity:
    """Lower-cased bot account names (loop guard) and the handles that address HootPR."""

    usernames: frozenset[str]
    mentions: frozenset[str]


def bot_identity(
    settings: Settings, provider: ProviderName, gitlab_bot_username: str | None
) -> BotIdentity:
    if provider == "github":
        slug = settings.github_app_slug.lower()
        return BotIdentity(frozenset({f"{slug}[bot]"}), frozenset({slug, f"{slug}[bot]"}))
    names = frozenset({gitlab_bot_username.lower()}) if gitlab_bot_username else frozenset()
    return BotIdentity(names, names)


def is_bot_author(identity: BotIdentity, username: str) -> bool:
    """HootPR itself or any other bot account: never act on these (loop guard, R4)."""
    u = username.lower()
    return u in identity.usernames or u.endswith("[bot]")


def primary_mention(identity: BotIdentity) -> str:
    return "@" + min(identity.mentions, key=len) if identity.mentions else "@hootpr"
