"""GitLab side of Change Stack: user-authored reviews and merges (spec §10.5)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.platforms.base import PlatformError, RepoRef, ReviewEvent
from app.platforms.http import HttpClient
from app.platforms.workspace import MergeMethod, MergeResult, UserReviewComment


class GitLabWorkspaceMixin:
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
        """Positioned discussions + a summary note, then approve / unapprove the MR.

        GitLab has no review object: the returned ref is the summary note id (or the last
        discussion id). Unlike the bot's ``post_review`` an approval failure is raised."""
        base = f"/projects/{repo.provider_repo_id}/merge_requests/{number}"
        ref = ""
        if comments:
            refs = self._http.get_json(base)["diff_refs"]
            for c in comments:
                position: dict[str, Any] = {
                    "position_type": "text",
                    "base_sha": refs["base_sha"],
                    "start_sha": refs["start_sha"],
                    "head_sha": refs["head_sha"],
                    "new_path": c.path,
                    "old_path": c.path,
                }
                position["old_line" if c.side == "LEFT" else "new_line"] = c.line
                d = self._http.request(
                    "POST", f"{base}/discussions", json={"body": c.body, "position": position}
                ).json()
                ref = str(d["id"])
        if body:
            ref = str(self._http.request("POST", f"{base}/notes", json={"body": body}).json()["id"])
        if event == "APPROVE":
            self._http.request("POST", f"{base}/approve", json={"sha": head_sha})
        elif event == "REQUEST_CHANGES":
            try:
                self._http.request("POST", f"{base}/unapprove")
            except PlatformError as exc:
                if exc.status_code not in (401, 403, 404):  # not approved by this user
                    raise
        return ref

    def merge_pull_request(
        self,
        repo: RepoRef,
        number: int,
        *,
        method: MergeMethod = "merge",
        sha: str | None = None,
        commit_title: str | None = None,
    ) -> MergeResult:
        """``PUT /merge_requests/:iid/merge`` (``rebase`` rebases first, then merges)."""
        base = f"/projects/{repo.provider_repo_id}/merge_requests/{number}"
        data: dict[str, Any] = {"squash": method == "squash"}
        if sha:
            data["sha"] = sha
        if commit_title:
            data["squash_commit_message" if method == "squash" else "merge_commit_message"] = (
                commit_title
            )
        try:
            if method == "rebase":
                self._http.request("PUT", f"{base}/rebase")
            d = self._http.request("PUT", f"{base}/merge", json=data).json()
        except PlatformError as exc:
            if exc.status_code in (401, 405, 406, 409, 422):
                return MergeResult(merged=False, sha=None, message=_reason(exc))
            raise
        merged = d.get("state") == "merged"
        return MergeResult(
            merged=merged,
            sha=str(d.get("merge_commit_sha") or d.get("squash_commit_sha") or "") or None,
            message="Merge request merged" if merged else f"Merge state: {d.get('state')}",
        )


def _reason(exc: PlatformError) -> str:
    if exc.status_code == 409:
        return "The head changed since you loaded it (SHA mismatch); refresh and try again."
    if exc.status_code in (405, 406, 422):
        return "GitLab says this merge request cannot be merged (draft, conflicts or pipeline)."
    return "GitLab rejected the merge (check your permissions on this project)."
