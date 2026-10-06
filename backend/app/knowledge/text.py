"""Learning text hygiene: credential redaction + validation (phase-3 R14)."""

import re

from app.review.safety import looks_like_injection

MAX_LEARNING_CHARS = 1000
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    ),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    ),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("razorpay-key", re.compile(r"\brzp_(?:live|test)_[A-Za-z0-9]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)


class InvalidLearning(ValueError):
    """Learning text that must not be stored; the message is shown to the user."""


def redact_secrets(text: str) -> str:
    """Replace credential-looking substrings with ``[REDACTED <kind>]``."""
    for kind, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED {kind}]", text)
    return text


def clean_learning_text(text: str) -> str:
    """Strip, collapse blank-line runs and redact; raise :class:`InvalidLearning` when the text
    is empty, longer than :data:`MAX_LEARNING_CHARS` or looks like a prompt injection."""
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not cleaned:
        raise InvalidLearning("learning text is empty")
    if len(cleaned) > MAX_LEARNING_CHARS:
        raise InvalidLearning(f"learning text is longer than {MAX_LEARNING_CHARS} characters")
    if looks_like_injection(cleaned):
        raise InvalidLearning(
            "learning text looks like an instruction to the AI, not a code preference"
        )
    return redact_secrets(cleaned)
