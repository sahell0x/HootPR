"""GitLab webhook token verification + normalization into PlatformEvent."""

from __future__ import annotations

import hmac
from typing import Any, Literal

from app.events.models import (
    CommentCreated,
    EventPR,
    EventRepo,
    IssueOpened,
    PipelineFailed,
    PlatformEvent,
    PrEvent,
    PrEventKind,
)

_PUBLIC_VISIBILITY = 20
_MR_STATE: dict[str, Literal["open", "merged"]] = {"opened": "open", "merged": "merged"}
_SIMPLE_ACTIONS: dict[str, PrEventKind] = {
    "open": "pr_opened",
    "reopen": "pr_reopened",
    "close": "pr_closed",
    "merge": "pr_closed",
}


def verify_token(expected: str, header: str | None) -> bool:
    """Constant-time check of ``X-Gitlab-Token``; an unset secret never verifies."""
    if not expected or header is None:
        return False
    return hmac.compare_digest(expected.encode(), header.encode())


def extract_project_id(payload: dict[str, Any]) -> str | None:
    project = payload.get("project") or {}
    pid = project.get("id")
    return str(pid) if pid is not None else None


def _username(payload: dict[str, Any]) -> str:
    return str((payload.get("user") or {}).get("username", ""))


def _repo(p: dict[str, Any]) -> EventRepo:
    return EventRepo(
        provider="gitlab",
        provider_repo_id=str(p["id"]),
        full_name=str(p["path_with_namespace"]),
        default_branch=p.get("default_branch"),
        private=int(p.get("visibility_level", 0)) < _PUBLIC_VISIBILITY,
    )


def _pr(payload: dict[str, Any]) -> EventPR:
    # MR hooks carry no base SHA: it stays "" and the worker refreshes via get_pull_request.
    a = payload["object_attributes"]
    return EventPR(
        number=int(a["iid"]),
        title=str(a.get("title") or ""),
        body=str(a.get("description") or ""),
        author_username=_username(payload),
        state=_MR_STATE.get(str(a.get("state")), "closed"),
        is_draft=bool(a.get("draft") or a.get("work_in_progress")),
        base_ref=str(a.get("target_branch") or ""),
        head_ref=str(a.get("source_branch") or ""),
        base_sha="",
        head_sha=str((a.get("last_commit") or {}).get("id") or ""),
        labels=[str(lb["title"]) for lb in payload.get("labels") or []],
        url=str(a.get("url") or ""),
    )


def _mr_kind(payload: dict[str, Any]) -> PrEventKind | None:
    a = payload["object_attributes"]
    action = str(a.get("action") or "")
    if action in _SIMPLE_ACTIONS:
        return _SIMPLE_ACTIONS[action]
    if action == "update":
        if a.get("oldrev"):
            return "pr_synchronized"
        draft = (payload.get("changes") or {}).get("draft") or {}
        if draft.get("previous") is True and draft.get("current") is False:
            return "pr_ready"
        return "pr_updated"
    return None


def parse_event(
    event_header: str, payload: dict[str, Any], delivery_id: str
) -> PlatformEvent | None:
    """Normalize a verified GitLab delivery; ``None`` means "not interesting, ignore"."""
    kind = payload.get("object_kind")
    if kind == "merge_request":
        ev_kind = _mr_kind(payload)
        if ev_kind is None:
            return None
        return PrEvent(
            kind=ev_kind,
            provider="gitlab",
            delivery_id=delivery_id,
            repo=_repo(payload["project"]),
            pr=_pr(payload),
            before_sha=payload["object_attributes"].get("oldrev"),
            sender=_username(payload),
        )
    if kind == "note":
        a = payload["object_attributes"]
        if a.get("noteable_type") != "MergeRequest" or "merge_request" not in payload:
            return None
        pos = a.get("position") or {}
        return CommentCreated(
            provider="gitlab",
            delivery_id=delivery_id,
            repo=_repo(payload["project"]),
            pr_number=int(payload["merge_request"]["iid"]),
            comment_id=str(a["id"]),
            author_username=_username(payload),
            body=str(a.get("note") or ""),
            thread_ref=a.get("discussion_id"),
            is_review_comment=a.get("type") == "DiffNote",
            path=pos.get("new_path"),
            line=int(pos["new_line"]) if pos.get("new_line") is not None else None,
            url=str(a.get("url") or ""),
        )
    if kind == "issue":
        a = payload["object_attributes"]
        if a.get("action") != "open" or a.get("confidential"):
            return None  # confidential issues are never enriched (their text stays private)
        return IssueOpened(
            provider="gitlab",
            delivery_id=delivery_id,
            repo=_repo(payload["project"]),
            number=int(a["iid"]),
            title=str(a.get("title") or ""),
            body=str(a.get("description") or ""),
            author_username=_username(payload),
            url=str(a.get("url") or ""),
            labels=[str(lb["title"]) for lb in payload.get("labels") or []],
        )
    if kind == "pipeline":
        a = payload["object_attributes"]
        if a.get("status") != "failed":
            return None
        mr = payload.get("merge_request") or {}
        return PipelineFailed(
            provider="gitlab",
            delivery_id=delivery_id,
            repo=_repo(payload["project"]),
            sha=str(a["sha"]),
            pr_number=int(mr["iid"]) if mr.get("iid") else None,
            run_id=str(a["id"]) if a.get("id") is not None else None,
            ref=a.get("ref"),
            url=str(a.get("url") or ""),
        )
    return None
