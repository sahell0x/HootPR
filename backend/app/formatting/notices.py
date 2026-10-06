"""Notices that replace the walkthrough body (decision P6: one marker comment per PR)."""

import math
from decimal import Decimal

from app.billing.pricing import fmt_credits
from app.formatting.walkthrough import TIP, WALKTHROUGH_MARKER

SKIP_REASONS: dict[str, str] = {
    "ignored_by_description": "`@hootpr ignore` found in the description",
    "paused": "reviews are paused on this pull request",
    "auto_paused": "auto-paused after the configured number of reviewed commits",
    "auto_review_disabled": "automatic reviews are disabled",
    "incremental_disabled": "incremental reviews are disabled",
    "draft": "draft pull request",
    "title_keyword": "title contains an ignore keyword",
    "ignored_user": "author is in ignore_usernames",
    "base_branch": "base branch is not configured for reviews",
    "label_excluded": "a label excludes this pull request",
    "label_missing": "a required label is missing",
    "description_keyword_missing": "the description keyword is missing",
    "superseded": "a newer commit was pushed",
    "pr_closed": "the pull request was closed",
    "no_reviewable_files": "no reviewable files (every changed file was excluded)",
}


def _human(reason: str) -> str:
    return SKIP_REASONS.get(reason, reason)


def skip_title(reason: str) -> str:
    return f"Skipped: {_human(reason)}"


def skipped_notice(reason: str) -> str:
    return "\n".join(
        [
            WALKTHROUGH_MARKER,
            "## Review skipped",
            "",
            f"HootPR did not review this commit: {_human(reason)}.",
            "Comment `@hootpr review` to request a review anyway.",
            "",
            "---",
            TIP,
        ]
    )


def rate_limited_notice(limit: int, retry_after_s: int) -> str:
    minutes = max(1, math.ceil(retry_after_s / 60))
    return "\n".join(
        [
            WALKTHROUGH_MARKER,
            "## Review rate limited",
            "",
            f"This organization used its {limit} reviews for the past hour. "
            f"Retry in about {minutes}m by commenting `@hootpr review`.",
            "",
            "Comment `@hootpr rate limit` to see the remaining allowance.",
            "",
            "---",
            TIP,
        ]
    )


def out_of_credits_notice(
    balance: Decimal, billing_url: str, minimum: Decimal | None = None
) -> str:
    need = f" and at least {fmt_credits(minimum)} to start" if minimum is not None else ""
    return "\n".join(
        [
            WALKTHROUGH_MARKER,
            "## Out of credits",
            "",
            f"This organization has {fmt_credits(balance)} credits left. Reviews are metered by AI "
            f"usage (typically about 100 credits){need}.",
            f"An admin can top up at {billing_url}.",
            "",
            "---",
            TIP,
        ]
    )


def error_notice(detail: str | None = None) -> str:
    lines = [
        WALKTHROUGH_MARKER,
        "## Review failed",
        "",
        "HootPR hit an error, no credit was charged. Comment `@hootpr review` to try again later.",
        "",
    ]
    if detail:
        lines += [detail, ""]
    return "\n".join([*lines, "---", TIP])
