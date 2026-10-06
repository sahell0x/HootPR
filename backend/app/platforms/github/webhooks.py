"""GitHub webhook signature verification + normalization into PlatformEvent."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Literal

from app.events.models import (
    CommentCreated,
    EventPR,
    EventRepo,
    InstallationAccount,
    InstallationAction,
    InstallationChanged,
    IssueOpened,
    PipelineFailed,
    PlatformEvent,
    PrEvent,
    PrEventKind,
    ThreadStatusChanged,
)

_PR_ACTIONS: dict[str, PrEventKind] = {
    "opened": "pr_opened",
    "synchronize": "pr_synchronized",
    "reopened": "pr_reopened",
    "ready_for_review": "pr_ready",
    "closed": "pr_closed",
}
_INSTALL_ACTIONS: dict[str, InstallationAction] = {
    "created": "created",
    "deleted": "deleted",
    "suspend": "suspend",
    "unsuspend": "unsuspend",
}
_REPO_ACTIONS: dict[str, InstallationAction] = {
    "added": "repos_added",
    "removed": "repos_removed",
}


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time check of ``X-Hub-Signature-256``; an unset secret never verifies."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def event_action(payload: dict[str, Any]) -> str | None:
    action = payload.get("action")
    return str(action) if action is not None else None


def _repo(r: dict[str, Any]) -> EventRepo:
    return EventRepo(
        provider="github",
        provider_repo_id=str(r["id"]),
        full_name=str(r["full_name"]),
        default_branch=r.get("default_branch"),
        private=bool(r.get("private", False)),
    )


def _pr(p: dict[str, Any]) -> EventPR:
    state: Literal["open", "closed", "merged"] = (
        "merged" if p.get("merged_at") else "open" if p.get("state") == "open" else "closed"
    )
    return EventPR(
        number=int(p["number"]),
        title=str(p.get("title") or ""),
        body=str(p.get("body") or ""),
        author_username=str(p["user"]["login"]),
        state=state,
        is_draft=bool(p.get("draft")),
        base_ref=str(p["base"]["ref"]),
        head_ref=str(p["head"]["ref"]),
        base_sha=str(p["base"]["sha"]),
        head_sha=str(p["head"]["sha"]),
        labels=[str(lb["name"]) for lb in p.get("labels", [])],
        url=str(p.get("html_url") or ""),
    )


def _installation_id(payload: dict[str, Any]) -> int | None:
    inst = payload.get("installation")
    return int(inst["id"]) if inst else None


def _sender(payload: dict[str, Any]) -> str:
    return str((payload.get("sender") or {}).get("login", ""))


def _account(acc: dict[str, Any]) -> InstallationAccount:
    return InstallationAccount(
        id=str(acc["id"]),
        login=str(acc["login"]),
        type="Organization" if acc.get("type") == "Organization" else "User",
        avatar_url=acc.get("avatar_url"),
    )


def _installation_event(
    event_name: str, action: str | None, payload: dict[str, Any], delivery_id: str
) -> InstallationChanged | None:
    inst = payload["installation"]
    if event_name == "installation" and action in _INSTALL_ACTIONS:
        return InstallationChanged(
            delivery_id=delivery_id,
            action=_INSTALL_ACTIONS[action],
            installation_id=int(inst["id"]),
            account=_account(inst["account"]),
            repositories_added=[_repo(r) for r in payload.get("repositories") or []],
        )
    if event_name == "installation_repositories" and action in _REPO_ACTIONS:
        return InstallationChanged(
            delivery_id=delivery_id,
            action=_REPO_ACTIONS[action],
            installation_id=int(inst["id"]),
            account=_account(inst["account"]),
            repositories_added=[_repo(r) for r in payload.get("repositories_added") or []],
            repositories_removed=[_repo(r) for r in payload.get("repositories_removed") or []],
        )
    return None


def _association(comment: dict[str, Any]) -> str | None:
    value = comment.get("author_association")
    return str(value) if value else None


def parse_event(event_name: str, payload: dict[str, Any], delivery_id: str) -> PlatformEvent | None:
    """Normalize a verified GitHub delivery; ``None`` means "not interesting, ignore"."""
    action = event_action(payload)
    if event_name == "pull_request" and action in _PR_ACTIONS:
        return PrEvent(
            kind=_PR_ACTIONS[action],
            provider="github",
            delivery_id=delivery_id,
            repo=_repo(payload["repository"]),
            pr=_pr(payload["pull_request"]),
            installation_id=_installation_id(payload),
            before_sha=payload.get("before"),
            sender=_sender(payload),
        )
    if event_name in ("installation", "installation_repositories"):
        return _installation_event(event_name, action, payload, delivery_id)
    if (
        event_name == "issue_comment"
        and action == "created"
        and "pull_request" in (payload.get("issue") or {})
    ):
        c = payload["comment"]
        return CommentCreated(
            provider="github",
            delivery_id=delivery_id,
            repo=_repo(payload["repository"]),
            pr_number=int(payload["issue"]["number"]),
            comment_id=str(c["id"]),
            author_username=str(c["user"]["login"]),
            body=str(c.get("body") or ""),
            installation_id=_installation_id(payload),
            url=str(c.get("html_url") or ""),
            author_association=_association(c),
        )
    if event_name == "pull_request_review_comment" and action == "created":
        c = payload["comment"]
        return CommentCreated(
            provider="github",
            delivery_id=delivery_id,
            repo=_repo(payload["repository"]),
            pr_number=int(payload["pull_request"]["number"]),
            comment_id=str(c["id"]),
            author_username=str(c["user"]["login"]),
            body=str(c.get("body") or ""),
            thread_ref=str(c.get("in_reply_to_id") or c["id"]),
            installation_id=_installation_id(payload),
            is_review_comment=True,
            path=str(c["path"]) if c.get("path") else None,
            line=_int(c.get("line") or c.get("original_line")),
            diff_hunk=c.get("diff_hunk"),
            url=str(c.get("html_url") or ""),
            author_association=_association(c),
        )
    if event_name == "pull_request_review_thread" and action in ("resolved", "unresolved"):
        comments = (payload.get("thread") or {}).get("comments") or []
        if not comments:
            return None
        return ThreadStatusChanged(
            provider="github",
            delivery_id=delivery_id,
            repo=_repo(payload["repository"]),
            pr_number=int(payload["pull_request"]["number"]),
            thread_ref=str(comments[0]["id"]),
            resolved=action == "resolved",
            installation_id=_installation_id(payload),
        )
    if (
        event_name == "issues"
        and action == "opened"
        and "pull_request" not in (payload.get("issue") or {})
    ):
        i = payload["issue"]
        return IssueOpened(
            provider="github",
            delivery_id=delivery_id,
            repo=_repo(payload["repository"]),
            number=int(i["number"]),
            title=str(i.get("title") or ""),
            body=str(i.get("body") or ""),
            author_username=str((i.get("user") or {}).get("login") or ""),
            url=str(i.get("html_url") or ""),
            labels=[str(lb["name"]) for lb in i.get("labels") or []],
            installation_id=_installation_id(payload),
        )
    if event_name == "workflow_run":
        return _workflow_run(payload, delivery_id)
    return None


_FAILED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})


def _workflow_run(payload: dict[str, Any], delivery_id: str) -> PipelineFailed | None:
    """A completed, failed GitHub Actions run (Phase 4 CI analysis / fix CI)."""
    run = payload.get("workflow_run") or {}
    if payload.get("action") != "completed" or run.get("conclusion") not in _FAILED_CONCLUSIONS:
        return None
    repo = _repo(payload["repository"])
    prs = [
        p
        for p in run.get("pull_requests") or []
        if str(((p.get("base") or {}).get("repo") or {}).get("id") or repo.provider_repo_id)
        == repo.provider_repo_id
    ]
    return PipelineFailed(
        provider="github",
        delivery_id=delivery_id,
        repo=repo,
        sha=str(run.get("head_sha") or ""),
        pr_number=int(prs[0]["number"]) if prs else None,
        run_id=str(run["id"]) if run.get("id") is not None else None,
        ref=run.get("head_branch"),
        url=str(run.get("html_url") or ""),
        installation_id=_installation_id(payload),
    )


def _int(v: Any) -> int | None:
    return int(v) if v is not None else None
