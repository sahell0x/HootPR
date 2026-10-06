"""Deterministic reply bodies for ``@hootpr`` commands (CodeRabbit-style, phase-3 spec §4)."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.billing.pricing import fmt_credits
from app.chat.commands import COMMANDS
from app.formatting.walkthrough import harden_warning
from app.knowledge.base import LearningHit
from app.knowledge.learnings import AddedLearning

INCREMENTAL_NOTE = (
    "HootPR is an incremental review system and does not re-review already reviewed commits. "
    "Use `{mention} full review` to review everything again."
)


def chat_marker(chat_id: UUID) -> str:
    """Hidden marker of a top-level reply (lets a retry edit instead of posting twice)."""
    return f"<!-- hootpr:chat:{chat_id} -->"


# Markdown that only renders at the start of a line (a fence, heading, list, quote, table).
_BLOCK_START = re.compile(r"(```|~~~|#{1,6} |[-*+] |\d+[.)] |> |\|)")


def with_author(author: str, body: str) -> str:
    """`@author` before the body; on its own line when the body opens with block markdown,
    which would not render after the mention (a ```python fence glued to it breaks the code)."""
    if _BLOCK_START.match(body.lstrip()):
        return f"@{author}\n\n{body.lstrip()}"
    return f"@{author} {body}"


def humanize_seconds(s: int) -> str:
    return "now" if s <= 0 else f"in {max(1, math.ceil(s / 60))}m"


def render_actions(author: str, lines: Sequence[str], note: str | None = None) -> str:
    parts = [
        f"@{author}",
        "",
        "<details>",
        "<summary>✅ Actions performed</summary>",
        "",
        "\n".join(lines),
        "",
    ]
    if note:
        parts += [f"> {note}", ""]
    return "\n".join([*parts, "</details>"])


def render_help(mention: str, schema_url: str) -> str:
    rows = [f"| `{mention} {c.phrases[0]}` | {c.help} |" for c in COMMANDS if c.name != "ignore"]
    return "\n".join(
        [
            "## HootPR commands",
            "",
            "| Command | What it does |",
            "|---|---|",
            *rows,
            "",
            f"Put `{mention} ignore` in the PR description to never review a pull request, and "
            f"`{mention} summary` in the description to place the summary there.",
            "",
            "Reply in any HootPR review thread to chat. Credits are metered by AI usage: a review "
            "typically costs about 100 credits and a chat reply less.",
            "",
            f"Configuration: add a `.hootpr.yaml` (schema: {schema_url}).",
        ]
    )


def render_configuration_reply(author: str, yaml_text: str, warnings: Sequence[str]) -> str:
    if not yaml_text.endswith("\n"):
        yaml_text += "\n"
    body = (
        f"@{author} Effective configuration for this pull request:\n\n"
        "<details>\n<summary>⚙️ Configuration</summary>\n\n"
        f"```yaml\n{yaml_text}```\n\n</details>"
    )
    if warnings:
        body += "\n\n**Warnings:**\n" + "\n".join(f"- {harden_warning(w)}" for w in warnings)
    return body


@dataclass(frozen=True)
class RateLimitInfo:
    reviews_limit: int
    reviews_remaining: int
    reviews_retry_s: int
    chat_limit: int
    chat_remaining: int
    chat_retry_s: int
    balance: Decimal
    typical_review: Decimal  # display-only typical metered prices
    typical_chat: Decimal
    billing_url: str


def _num(d: Decimal) -> str:
    return fmt_credits(d)


def render_rate_limit(author: str, info: RateLimitInfo) -> str:
    return "\n".join(
        [
            f"@{author} Usage for this organization (sliding one-hour window):",
            "",
            "| | Remaining | Next slot |",
            "|---|---|---|",
            f"| Reviews | {info.reviews_remaining} of {info.reviews_limit} | "
            f"{humanize_seconds(info.reviews_retry_s)} |",
            f"| Chat replies | {info.chat_remaining} of {info.chat_limit} | "
            f"{humanize_seconds(info.chat_retry_s)} |",
            "",
            f"**Credit balance:** {_num(info.balance)} credits (metered by AI usage: a review "
            f"typically costs about {_num(info.typical_review)}, a chat reply about "
            f"{_num(info.typical_chat)}). Top up: {info.billing_url}",
        ]
    )


def render_unsupported(author: str, phrase: str) -> str:
    return f"@{author} `{phrase}` is not available in HootPR yet."


def render_hint(author: str, text: str) -> str:
    return with_author(author, text)


def render_chat_rate_limited(author: str, limit: int, retry_after_s: int) -> str:
    return (
        f"@{author} Chat rate limited — {limit} replies per hour per organization. "
        f"Try again {humanize_seconds(retry_after_s)}. No credit was charged."
    )


def render_chat_out_of_credits(
    author: str, balance: Decimal, minimum: Decimal, billing_url: str
) -> str:
    """Like ``out_of_credits_notice`` but without the walkthrough marker (a chat reply must never
    be mistaken for the walkthrough comment)."""
    return "\n".join(
        [
            f"@{author} **Out of credits.** This organization has {_num(balance)} credits left "
            f"and a chat reply needs at least {_num(minimum)} to start (replies are metered by "
            "AI usage).",
            f"An admin can top up at {billing_url}.",
        ]
    )


def _fence_safe(text: str) -> str:
    """Learning text inside a fenced block: a stray fence must not close it early."""
    return text.replace("```", "`​``")


def render_chat_reply(
    author: str,
    answer: str,
    added: Sequence[AddedLearning],
    used: Sequence[LearningHit],
    *,
    pr_ref: str,
    location: str | None,
    now: datetime,
) -> str:
    """A chat answer with CodeRabbit's "✏️ Learnings added" / "🧠 Learnings used" sections."""
    parts = [with_author(author, answer)]
    if added:
        stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        blocks: list[str] = []
        for a in added:
            head = [f"Learnt from: {author}", f"PR: {pr_ref}"]
            if location:
                head.append(f"File: {_fence_safe(' '.join(location.split()))}")
            head.append(f"Timestamp: {stamp}")
            blocks.append("```\n" + "\n".join(head) + f"\n\nLearning: {_fence_safe(a.text)}\n```")
        parts.append(
            "<details>\n<summary>✏️ Learnings added</summary>\n\n"
            + "\n\n".join(blocks)
            + "\n\n</details>"
        )
    if used:
        blocks = [f"```\nLearning: {_fence_safe(' '.join(h.text.split()))}\n```" for h in used]
        parts.append(
            "<details>\n<summary>🧠 Learnings used</summary>\n\n"
            + "\n\n".join(blocks)
            + "\n\n</details>"
        )
    return "\n\n".join(parts)


def render_chat_error(author: str) -> str:
    return (
        f"@{author} HootPR hit an error while answering this. No credit was charged — please "
        "try again later."
    )
