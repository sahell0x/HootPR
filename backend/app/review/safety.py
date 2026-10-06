"""Prompt-injection-aware wrapping and output hardening (spec §7.8, plan Q16)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.review.findings import Candidate

if TYPE_CHECKING:
    from app.settings import Settings

TITLE_MAX, BODY_MAX, SUGGESTION_MAX, EVIDENCE_MAX = 80, 1200, 5000, 500
MAX_EVIDENCE_ITEMS = 10
DOC_HOSTS = frozenset(
    {
        "docs.python.org",
        "peps.python.org",
        "developer.mozilla.org",
        "owasp.org",
        "cheatsheetseries.owasp.org",
        "cwe.mitre.org",
        "nvd.nist.gov",
        "go.dev",
        "pkg.go.dev",
        "doc.rust-lang.org",
        "docs.oracle.com",
        "learn.microsoft.com",
        "nodejs.org",
        "react.dev",
        "www.typescriptlang.org",
        "eslint.org",
        "docs.astral.sh",
        "semgrep.dev",
    }
)
_CODE = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")
_MENTION = re.compile(
    r"(?<![\w@/.])@([A-Za-z0-9][A-Za-z0-9-]{0,38}(?:/[A-Za-z0-9_.-]+)?(?:\[bot\])?)"
)
_TAG = re.compile(r"<!--[\s\S]*?-->|</?(?!(?:details|summary)\b)[A-Za-z][^>]*>", re.I)
# Absolute and scheme-relative links, plus bare ``www.`` hosts that GitHub/GitLab autolink.
_URL = re.compile(
    r"(?:https?:)?//[A-Za-z0-9][^\s<>()\[\]`'\"]*|(?<![\w.@/-])www\.[A-Za-z0-9][^\s<>()\[\]`'\"]*",
    re.I,
)
# GitLab runs any line of a note/description starting with ``/`` as a quick action (/merge,
# /approve, /close ...) with the bot's permissions: model text must never start a line with it.
_QUICK_ACTION = re.compile(r"(?m)^([ \t]*)/")
_UNTRUSTED_TAG = re.compile(r"<(?=\s*/?\s*untrusted)", re.I)
_MERMAID_LINK = re.compile(r"(?im)^\s*(?:click|link|links)\b.*$\n?")
_INJECTION = re.compile(
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above) instructions"
    r"|disregard (?:the |your )?(?:system|previous|prior) (?:prompt|instructions)"
    r"|(?:reveal|print|repeat) (?:your|the) system prompt"
    r"|you are now|approve this (?:pr|pull request|merge request)"
    r"|as an ai (?:language )?model",
    re.I,
)


def untrusted(source: str, text: str) -> str:
    """Wrap repo-controlled text so prompts can tell the model never to obey it (spec §7.8)."""
    src = re.sub(r"[^A-Za-z0-9:_./@-]", "_", source)[:200]
    body = _UNTRUSTED_TAG.sub("&lt;", text)  # any case/whitespace variant of the tags
    return f'<untrusted source="{src}">\n{body}\n</untrusted>'


def repo_host(provider: str, settings: Settings | None = None) -> str:
    """Web host of the repository (self-managed GitLab: ``GITLAB_BASE_URL``)."""
    if provider == "gitlab":
        url = settings.gitlab_base_url if settings is not None else "https://gitlab.com"
    else:
        url = settings.github_web_url if settings is not None else "https://github.com"
    return _host(url) or ("gitlab.com" if provider == "gitlab" else "github.com")


def _outside_code(text: str, fn: Callable[[str], str]) -> str:
    parts = _CODE.split(text)
    return "".join(p if i % 2 else fn(p) for i, p in enumerate(parts))


def neutralize_mentions(text: str, allow: frozenset[str] = frozenset()) -> str:
    """Insert a zero-width space after ``@`` so nobody is pinged; code spans are left alone."""

    def fix(segment: str) -> str:
        return _MENTION.sub(
            lambda m: m.group(0) if m.group(1).lower() in allow else "@​" + m.group(1),
            segment,
        )

    return _outside_code(text, fix)


def strip_html(text: str) -> str:
    """Remove raw HTML tags and comments except ``<details>``/``<summary>``, outside code."""
    return _outside_code(text, lambda s: _TAG.sub("", s))


def _host_ok(host: str, allowed: frozenset[str]) -> bool:
    return host in allowed or host in DOC_HOSTS or any(host.endswith("." + d) for d in DOC_HOSTS)


def _host(url: str) -> str:
    if url.lower().startswith("www."):
        url = "http://" + url
    elif url.startswith("//"):
        url = "http:" + url
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def disallowed_urls(text: str, host: str) -> list[str]:
    """URLs pointing outside the repo's host and the documentation allowlist."""
    return [u for u in _URL.findall(text) if not _host_ok(_host(u), frozenset({host}))]


def scrub_urls(
    text: str, allowed_hosts: frozenset[str] = frozenset({"github.com", "gitlab.com"})
) -> str:
    """Replace links outside the allowlist with ``[link removed]``; code spans are left alone
    (a quoted ``http://localhost:8080`` in code is not a link)."""

    def fix(segment: str) -> str:
        return _URL.sub(
            lambda m: (
                m.group(0) if _host_ok(_host(m.group(0)), allowed_hosts) else "[link removed]"
            ),
            segment,
        )

    return _outside_code(text, fix)


def neutralize_quick_actions(text: str) -> str:
    """Escape a leading ``/`` (``\\/merge`` renders as ``/merge`` but is no GitLab command)."""
    return _outside_code(text, lambda s: _QUICK_ACTION.sub(lambda m: m.group(1) + "\\/", s))


def strip_mermaid_links(diagram: str) -> str:
    """Mermaid ``click``/``link``/``links`` directives carry URLs and callbacks: remove them."""
    return _MERMAID_LINK.sub("", diagram)


def looks_like_injection(text: str) -> bool:
    return _INJECTION.search(text) is not None


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def harden_text(text: str, max_len: int, allow_mentions: frozenset[str] = frozenset()) -> str:
    """Every model-written text posted anywhere: no pings, raw HTML, hidden comments or GitLab
    quick actions."""
    t = neutralize_mentions(strip_html(text), allow_mentions).replace("<!--", "<​!--")
    return _truncate(neutralize_quick_actions(t), max_len)


def clean_prose(text: str, max_len: int, host: str | None = None) -> str:
    """Model prose we keep (walkthrough, summaries, poem): foreign links scrubbed, hardened."""
    allowed = frozenset({"github.com", "gitlab.com", *([host] if host else [])})
    return harden_text(scrub_urls(text, allowed), max_len)


def harden_candidate(c: Candidate, host: str) -> bool:
    """Harden a finding in place before posting; returns False (and drops it) when refused.

    Foreign links in the prose are scrubbed (not a reason to lose the finding); URLs inside
    code spans are quoted code. A suggestion introducing a foreign URL loses the suggestion."""
    if looks_like_injection(f"{c.title}\n{c.body}"):
        c.drop("not_code_related")
        return False
    allowed = frozenset({host})
    c.title = harden_text(scrub_urls(" ".join(c.title.split()), allowed), TITLE_MAX)
    c.body = harden_text(scrub_urls(c.body, allowed), BODY_MAX)
    if c.suggestion is not None and (
        len(c.suggestion) > SUGGESTION_MAX
        or "```" in c.suggestion
        or disallowed_urls(c.suggestion, host)
    ):
        c.suggestion = None
    c.evidence = [_truncate(e, EVIDENCE_MAX) for e in c.evidence[:MAX_EVIDENCE_ITEMS]]
    return True
