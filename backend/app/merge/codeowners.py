"""CODEOWNERS parsing (GitHub + GitLab syntax) and file-path extraction from issue text, for
suggested assignees (spec §10.2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS")
MAX_RULES = 1000
_PATH_TOKEN = re.compile(
    r"(?<![\w@:/.-])((?:[\w.-]+/)*[\w-]+\.[A-Za-z][A-Za-z0-9]{0,7}|(?:[\w.-]+/)+[\w.-]+)"
    r"(?![\w/])"
)


@dataclass(frozen=True)
class OwnerRule:
    pattern: str
    regex: re.Pattern[str]
    owners: tuple[str, ...]


def _to_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    p = pattern.strip("/")
    directory = pattern.endswith("/")
    out = []
    i = 0
    while i < len(p):
        if p.startswith("**", i):
            out.append(".*")
            i += 2
            if i < len(p) and p[i] == "/":
                i += 1
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    body = "".join(out)
    prefix = "^" if anchored else "^(?:.*/)?"
    # A plain name matches the file or everything under a directory of that name.
    suffix = "/.*$" if directory else "(?:/.*)?$"
    return re.compile(prefix + body + suffix)


def parse_codeowners(text: str) -> list[OwnerRule]:
    rules: list[OwnerRule] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("[", "^[")):  # GitLab section headers
            continue
        parts = line.split()
        if len(parts) < 2 and not parts[0]:
            continue
        pattern, owners = parts[0], tuple(parts[1:])
        try:
            rules.append(OwnerRule(pattern, _to_regex(pattern), owners))
        except re.error:
            continue
        if len(rules) >= MAX_RULES:
            break
    return rules


def owners_for(rules: Sequence[OwnerRule], path: str) -> tuple[str, ...]:
    """The last matching rule wins (GitHub/GitLab semantics)."""
    path = path.lstrip("/")
    found: tuple[str, ...] = ()
    for r in rules:
        if r.regex.match(path):
            found = r.owners
    return found


def user_owners(owners: Sequence[str]) -> list[str]:
    """Individual users only (``@user``); teams/groups and emails cannot be assigned."""
    return [o[1:] for o in owners if o.startswith("@") and "/" not in o and len(o) > 1]


def paths_in_text(text: str, limit: int = 5) -> list[str]:
    out: list[str] = []
    for m in _PATH_TOKEN.finditer(text or ""):
        p = m.group(1).strip("./")
        if p and "://" not in p and p not in out and not re.fullmatch(r"[\d.]+", p):
            out.append(p)
        if len(out) >= limit:
            break
    return out
