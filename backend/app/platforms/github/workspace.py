"""GitHub side of Change Stack: user-authored reviews and merges (spec §10.5)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.platforms.base import PlatformError, RepoRef, ReviewEvent
from app.platforms.http import HttpClient
from app.platforms.workspace import MergeMethod, MergeResult, UserReviewComment


class GitHubWorkspaceMixin:
    _http: HttpClient

    def submit_review(
        self,
        repo: RepoRef,
        number: int,
        head_sha: str,
        event: ReviewEvent,
        body: str,
        comments: Sequence[UserReviewComment] = (),
    ) -> str:
        """One pull request review with the given verdict; returns the review id."""
        payload: list[dict[str, Any]] = []
        for c in comments:
            item: dict[str, Any] = {"path": c.path, "line": c.line, "side": c.side, "body": c.body}
            if c.start_line is not None and c.start_line < c.line:
                item["start_line"], item["start_side"] = c.start_line, c.side
            payload.append(item)
        data: dict[str, Any] = {"commit_id": head_sha, "event": event, "comments": payload}
        if body or event != "APPROVE":
            data["body"] = body
        d = self._http.request(
            "POST", f"/repos/{repo.full_name}/pulls/{number}/reviews", json=data
        ).json()
        return str(d["id"])

    def merge_pull_request(
        self,
        repo: RepoRef,
        number: int,
        *,
        method: MergeMethod = "merge",
        sha: str | None = None,
        commit_title: str | None = None,
    ) -> MergeResult:
        """``PUT /pulls/{n}/merge``; ``sha`` makes GitHub refuse (409) if the head moved."""
        data: dict[str, Any] = {"merge_method": method}
        if sha:
            data["sha"] = sha
        if commit_title:
            data["commit_title"] = commit_title
        try:
            d = self._http.request(
                "PUT", f"/repos/{repo.full_name}/pulls/{number}/merge", json=data
            ).json()
        except PlatformError as exc:
            if exc.status_code in (405, 409, 422):
                return MergeResult(merged=False, sha=None, message=_reason(exc))
            raise
        return MergeResult(
            merged=bool(d.get("merged")),
            sha=str(d["sha"]) if d.get("sha") else None,
            message=str(d.get("message") or "Pull request merged"),
        )


def _reason(exc: PlatformError) -> str:
    if exc.status_code == 409:
        return "The head branch changed since you loaded it; refresh and try again."
    if exc.status_code == 405:
        return "GitHub says this pull request is not mergeable (checks, reviews or conflicts)."
    return "GitHub rejected the merge request."
