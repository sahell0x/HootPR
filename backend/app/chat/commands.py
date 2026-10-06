"""``@hootpr`` command parser (spec §8, phase-3 spec §4, R6).

A comment addresses HootPR when it mentions one of the bot's handles outside code spans, code
fences and quoted lines. The text on the rest of the mention's line is the command phrase; a
phrase that is not a known command makes the comment a free-form chat question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.chat.identity import BotIdentity
from app.finishing.commands import parse_finishing

CommandName = Literal[
    "review",
    "full_review",
    "pause",
    "resume",
    "resolve",
    "approve",
    "summary",
    "sequence_diagram",
    "configuration",
    "help",
    "rate_limit",
    "ignore",
    "finishing_touch",
    "ignore_pre_merge",
    "create_issue",
    "security_review",
    "unsupported",
]
Cost = Literal["free", "review", "chat"]
SEQUENCE_DIAGRAM_REQUEST = (
    "Generate a Mermaid sequence diagram (```mermaid sequenceDiagram```) of the control flow this "
    "pull request changes, followed by a two-sentence explanation."
)


@dataclass(frozen=True)
class CommandSpec:
    name: CommandName
    phrases: tuple[str, ...]
    cost: Cost
    top_level_only: bool
    help: str


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("review", ("review",), "review", False, "Review the new commits (incremental)."),
    CommandSpec(
        "full_review",
        ("full review",),
        "review",
        False,
        "Review the whole pull request from scratch.",
    ),
    CommandSpec("pause", ("pause",), "free", False, "Stop automatic reviews on this pull request."),
    CommandSpec("resume", ("resume",), "free", False, "Restart automatic reviews."),
    CommandSpec("resolve", ("resolve",), "free", True, "Resolve all HootPR review comments."),
    CommandSpec(
        "approve",
        ("approve",),
        "free",
        True,
        "Resolve all HootPR comments and approve (with `request_changes_workflow`).",
    ),
    CommandSpec(
        "summary",
        ("summary",),
        "chat",
        False,
        "Regenerate the “Summary by HootPR” in the description.",
    ),
    CommandSpec(
        "sequence_diagram",
        ("generate sequence diagram",),
        "chat",
        False,
        "Draw a sequence diagram of the change.",
    ),
    CommandSpec(
        "configuration",
        ("configuration", "config"),
        "free",
        False,
        "Show the effective HootPR configuration.",
    ),
    CommandSpec("help", ("help",), "free", False, "Show this list."),
    CommandSpec(
        "rate_limit",
        ("rate limit", "rate-limit", "limits", "quota"),
        "free",
        False,
        "Show remaining reviews/chat replies this hour and the credit balance.",
    ),
    CommandSpec(
        "ignore",
        ("ignore",),
        "free",
        False,
        "In the PR description: never review this pull request.",
    ),
    # Phase 4 finishing touches (append `commit` or `stacked pr` to choose the delivery).
    CommandSpec(
        "finishing_touch",
        ("generate docstrings",),
        "review",
        False,
        "Add missing docstrings to the changed code (stacked PR; `… commit` to commit).",
    ),
    CommandSpec(
        "finishing_touch",
        ("generate unit tests",),
        "review",
        False,
        "Write, run and fix unit tests for the changed code (stacked PR).",
    ),
    CommandSpec(
        "finishing_touch",
        ("autofix",),
        "review",
        False,
        "Apply the open HootPR suggestions and fixes (commit; `autofix stacked pr`).",
    ),
    CommandSpec(
        "finishing_touch",
        ("simplify",),
        "review",
        False,
        "Simplify the changed code without changing behaviour (stacked PR).",
    ),
    CommandSpec(
        "finishing_touch",
        ("fix ci", "fix-ci", "fixci"),
        "review",
        False,
        "Read the failed CI logs and push a fix (commit).",
    ),
    CommandSpec(
        "finishing_touch",
        ("resolve merge conflict",),
        "review",
        False,
        "Merge the base branch and resolve the conflicts (commit).",
    ),
    CommandSpec(
        "finishing_touch",
        ("run <recipe>",),
        "review",
        False,
        "Run a custom recipe from `reviews.finishing_touches.custom`.",
    ),
    CommandSpec(
        "ignore_pre_merge",
        ("ignore pre-merge checks", "ignore pre merge checks", "ignore premerge checks"),
        "free",
        False,
        "Override failing pre-merge checks on this pull request.",
    ),
    CommandSpec(
        "create_issue",
        ("create issue <text>",),
        "chat",
        False,
        "Create an issue from this conversation, linked back to the pull request.",
    ),
    CommandSpec(
        "security_review",
        ("security review",),
        "free",  # the repo-level job holds up to SECURITY_HOLD_MAX itself (phase 6, metered)
        False,
        "Security architecture review of the repository (metered by AI usage).",
    ),
)
# CodeRabbit commands HootPR recognizes but does not implement (yet): answered, never charged.
UNSUPPORTED_PHRASES: tuple[str, ...] = (
    "generate configuration",
    "local commit",
    "emit path instructions",
    "generate project vocabulary",
)
UNSUPPORTED_PREFIXES: tuple[str, ...] = ()
CREATE_ISSUE_PREFIX = "create issue"
_BY_PHRASE: dict[str, CommandName] = {p: c.name for c in COMMANDS for p in c.phrases}


@dataclass(frozen=True)
class ParsedComment:
    mentioned: bool
    command: CommandName | None
    phrase: str
    text: str


def spec_for(name: CommandName) -> CommandSpec:
    return next(c for c in COMMANDS if c.name == name)


def _blank(m: re.Match[str]) -> str:
    """Same-length replacement keeps offsets into the original body valid."""
    return re.sub(r"[^\n]", " ", m.group(0))


def _visible(body: str) -> str:
    """Body with fenced code, inline code and quoted lines blanked (mentions there don't count)."""
    body = re.sub(r"```.*?(?:```|\Z)", _blank, body, flags=re.S)
    body = re.sub(r"`[^`\n]*`", _blank, body)
    return re.sub(r"(?m)^[ \t]*>.*$", _blank, body)


def _mention_re(identity: BotIdentity) -> re.Pattern[str] | None:
    if not identity.mentions:
        return None
    names = "|".join(re.escape(m) for m in sorted(identity.mentions, key=len, reverse=True))
    return re.compile(rf"(?<![\w@./-])@(?:{names})(?![\w\[-])", re.I)


def has_mention(body: str, identity: BotIdentity) -> bool:
    rx = _mention_re(identity)
    return bool(rx and rx.search(_visible(body)))


def parse_comment(body: str, identity: BotIdentity) -> ParsedComment:
    rx = _mention_re(identity)
    visible = _visible(body)
    m = rx.search(visible) if rx else None
    if m is None:
        return ParsedComment(False, None, "", body.strip())
    rest = visible[m.end() :].split("\n", 1)[0]
    phrase = " ".join(rest.lower().split()).rstrip(".!?").strip(" ,:")
    text = (body[: m.start()] + body[m.end() :]).strip()
    if phrase in _BY_PHRASE:
        return ParsedComment(True, _BY_PHRASE[phrase], phrase, text)
    if phrase == CREATE_ISSUE_PREFIX or phrase.startswith(
        (CREATE_ISSUE_PREFIX + " ", CREATE_ISSUE_PREFIX + ":")
    ):
        return ParsedComment(True, "create_issue", phrase, text)
    if parse_finishing(phrase) is not None:
        return ParsedComment(True, "finishing_touch", phrase, text)
    if phrase in UNSUPPORTED_PHRASES or any(phrase.startswith(p) for p in UNSUPPORTED_PREFIXES):
        return ParsedComment(True, "unsupported", phrase, text)
    return ParsedComment(True, None, phrase, text)
