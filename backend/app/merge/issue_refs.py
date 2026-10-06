"""Linked-issue references in a PR description (spec §10.2).

Recognized (CodeRabbit/GitHub/GitLab parity):
- a keyword (``fixes``, ``closes``, ``resolves``, ``implements``, ``addresses``, ``relates to``,
  ``refs``, ``part of`` and their inflections) followed by one or more references:
  ``#12``, ``owner/repo#12``, ``group/sub/project#3`` or an issue URL;
- any issue URL of the provider's own host anywhere in the text
  (``https://github.com/o/r/issues/12``, ``https://gitlab.com/g/p/-/issues/3``).

Code fences, inline code, quoted lines and HootPR's own summary block are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

MAX_LINKED_ISSUES = 5
_KEYWORD = re.compile(
    r"(?<![\w-])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|implement(?:s|ed)?|address(?:es|ed)?"
    r"|relate[sd]?\s+to|refs?|part\s+of|see\s+also)\s*:?\s+",
    re.I,
)
# One reference, anchored where the previous one ended (after a keyword or a separator).
_REF = re.compile(
    r"(?:(?P<url>https?://[^\s)>\]]+)|(?P<repo>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)?#(?P<num>\d+))"
    r"(?![\w/])"
)
_SEP = re.compile(r"\s*(?:,|\band\b|&)?\s*", re.I)
_URL_ANYWHERE = re.compile(r"https?://[^\s)>\]]+")
_SUMMARY = re.compile(r"<!-- hootpr:summary:start -->.*?<!-- hootpr:summary:end -->", re.S)


@dataclass(frozen=True)
class IssueRef:
    """``repo`` is ``None`` for the PR's own repository."""

    repo: str | None
    number: int

    def key(self, own_repo: str) -> tuple[str, int]:
        return ((self.repo or own_repo).lower(), self.number)

    def label(self, own_repo: str) -> str:
        return f"#{self.number}" if self.repo in (None, own_repo) else f"{self.repo}#{self.number}"


def _blank(m: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _visible(text: str) -> str:
    text = _SUMMARY.sub(_blank, text)
    text = re.sub(r"```.*?(?:```|\Z)", _blank, text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", _blank, text)
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.S)
    return re.sub(r"(?m)^[ \t]*>.*$", _blank, text)


def parse_issue_url(url: str, web_host: str) -> IssueRef | None:
    """``https://<host>/<repo path>/issues/<n>`` or ``/-/issues/<n>`` on ``web_host`` only."""
    parsed = urlparse(url.rstrip(".,;:"))
    if (parsed.hostname or "").lower() != web_host.lower():
        return None
    m = re.fullmatch(r"/(?P<repo>[^?#]+?)(?:/-)?/issues/(?P<num>\d+)/?", parsed.path)
    if m is None or "/" not in m.group("repo"):
        return None
    return IssueRef(m.group("repo"), int(m.group("num")))


def parse_issue_refs(
    text: str, own_repo: str, web_host: str, *, limit: int = MAX_LINKED_ISSUES
) -> list[IssueRef]:
    """Linked issues in ``text`` in order of appearance, deduplicated, at most ``limit``."""
    body = _visible(text or "")
    found: dict[tuple[str, int], IssueRef] = {}

    def add(ref: IssueRef | None) -> None:
        if ref is not None and ref.number > 0:
            if ref.repo is not None and ref.repo.lower() == own_repo.lower():
                ref = IssueRef(None, ref.number)
            found.setdefault(ref.key(own_repo), ref)

    hits: list[tuple[int, IssueRef | None]] = []
    for kw in _KEYWORD.finditer(body):
        pos = kw.end()
        while True:
            m = _REF.match(body, pos)
            if m is None:
                break
            if m.group("url"):
                hits.append((m.start(), parse_issue_url(m.group("url"), web_host)))
            else:
                hits.append((m.start(), IssueRef(m.group("repo"), int(m.group("num")))))
            sep = _SEP.match(body, m.end())
            pos = sep.end() if sep else m.end()
    for m in _URL_ANYWHERE.finditer(body):
        hits.append((m.start(), parse_issue_url(m.group(0), web_host)))
    for _, ref in sorted(hits, key=lambda h: h[0]):
        add(ref)
    return list(found.values())[:limit]
