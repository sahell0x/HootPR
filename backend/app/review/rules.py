"""Auto-review rules (spec §6.6, §9.2 ``reviews.auto_review``)."""

import re
from dataclasses import dataclass
from typing import Literal

from app.config.schema import HootPRConfig

ReviewTrigger = Literal["auto", "incremental", "command_review", "command_full", "manual"]
AUTO_TRIGGERS: tuple[ReviewTrigger, ...] = ("auto", "incremental")


@dataclass(frozen=True)
class PrFacts:
    title: str
    body: str
    author_username: str
    is_draft: bool
    base_ref: str
    labels: tuple[str, ...]
    paused: bool
    reviewed_commits_count: int


def _base_allowed(patterns: list[str], base: str, default_branch: str) -> bool:
    if base == default_branch:
        return True
    for p in patterns:
        try:
            if re.fullmatch(p, base):
                return True
        except re.error:
            if p == base:
                return True
    return False


def should_review(
    config: HootPRConfig, pr: PrFacts, trigger: ReviewTrigger, default_branch: str
) -> str | None:
    """Return a skip reason, or ``None`` when the PR should be reviewed.

    Explicit commands (``@hootpr review``/``full review``, manual) bypass the automatic rules;
    only ``@hootpr ignore`` in the description applies to them (CodeRabbit behavior).
    """
    if "@hootpr ignore" in pr.body.lower():
        return "ignored_by_description"
    if trigger not in AUTO_TRIGGERS:
        return None
    ar = config.reviews.auto_review
    if pr.paused:
        return "paused"
    if not ar.enabled:
        return "auto_review_disabled"
    if trigger == "incremental" and not ar.auto_incremental_review:
        return "incremental_disabled"
    if pr.is_draft and not ar.drafts:
        return "draft"
    title = pr.title.lower()
    if any(k.lower() in title for k in ar.ignore_title_keywords if k):
        return "title_keyword"
    if pr.author_username in ar.ignore_usernames:
        return "ignored_user"
    if not _base_allowed(ar.base_branches, pr.base_ref, default_branch):
        return "base_branch"
    excluded = {lb[1:] for lb in ar.labels if lb.startswith("!")}
    required = {lb for lb in ar.labels if not lb.startswith("!")}
    if excluded & set(pr.labels):
        return "label_excluded"
    if required and not required & set(pr.labels):
        return "label_missing"
    if ar.description_keyword and ar.description_keyword not in pr.body:
        return "description_keyword_missing"
    limit = ar.auto_pause_after_reviewed_commits
    if trigger == "incremental" and limit > 0 and pr.reviewed_commits_count >= limit:
        return "auto_paused"
    return None
