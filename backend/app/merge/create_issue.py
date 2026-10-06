"""``@hootpr create issue <text>`` (spec §10.2): an issue drafted from the request and the PR
context, with a backlink to the comment that asked for it. Runs as a ``chat.run`` job (metered
like a chat reply, released if anything fails)."""

from __future__ import annotations

import re
from typing import Any, cast

from app.chat.replies import render_actions
from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.merge.prompts import CREATE_ISSUE_SYSTEM
from app.merge.schemas import IssueDraft
from app.models import ChatMessage
from app.platforms.base import GitPlatform, PullRequest, RepoRef
from app.review.llm import LLMLike
from app.review.prompts import system_prompt
from app.review.safety import clean_prose, repo_host, untrusted
from app.settings import Settings

_PREFIX = re.compile(r"^\s*create\s+issue\s*:?\s*", re.I)
TITLE_MAX = 80
BODY_MAX = 6000


def request_text(text: str) -> str:
    """The words after ``create issue`` (the mention is already removed)."""
    return _PREFIX.sub("", text, count=1).strip()


def fallback_title(req: str, pr_title: str) -> str:
    first = " ".join(req.split("\n", 1)[0].split())
    return (first or f"Follow-up from: {pr_title}")[:TITLE_MAX]


def create_issue_from_chat(
    platform: GitPlatform,
    ref: RepoRef,
    live: PullRequest,
    row: ChatMessage,
    text: str,
    cfg: HootPRConfig,
    llm: LLMLike,
    settings: Settings,
    trace: TraceContext,
) -> str:
    """Create the issue and return the reply body. Platform errors propagate (the chat job then
    refunds the hold and posts its error reply)."""
    host = repo_host(ref.provider, settings)
    req = request_text(text)
    meta: dict[str, Any] = row.meta or {}
    context = [untrusted("request", req or "(no details given)")]
    context.append(untrusted("pr", f"title: {live.title}\n\n{live.body[:3000]}"))
    if meta.get("path"):
        loc = f"{meta['path']}:{meta.get('line') or ''}"
        context.append(untrusted("location", f"{loc}\n{(meta.get('diff_hunk') or '')[:2000]}"))
    try:
        res = llm.complete(
            "cheap",
            [
                {"role": "system", "content": system_prompt(CREATE_ISSUE_SYSTEM, cfg)},
                {"role": "user", "content": "\n\n".join(context)},
            ],
            response_model=IssueDraft,
            max_output_tokens=1500,
            trace=trace,
        )
        draft = cast(IssueDraft, res.parsed)
        title = clean_prose(" ".join(draft.title.split()), TITLE_MAX, host)
        body = clean_prose(draft.body, BODY_MAX, host)
    except StructuredOutputError:
        title, body = "", clean_prose(req, BODY_MAX, host)
    title = title.strip() or fallback_title(clean_prose(req, 200, host), live.title)
    source = str(meta.get("url") or live.url)
    backlink = (
        f"\n\n---\nCreated by HootPR from {ref.full_name}#{live.number} "
        f"([comment]({source})) at the request of @{row.author_username}."
    )
    issue = platform.create_issue(ref, title, body + backlink)
    return render_actions(
        row.author_username, [f"Created issue [#{issue.number}]({issue.url}): {title}"]
    )
