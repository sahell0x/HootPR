"""GitLabPlatform: GitPlatform over the GitLab v4 API with the org's bot token."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from app.logging import get_logger
from app.platforms.base import (
    CheckState,
    CloneCredentials,
    Comment,
    FileDiff,
    FileStatus,
    GitPlatform,
    InlineComment,
    NotFoundError,
    PlatformError,
    ProviderName,
    PrState,
    PullRequest,
    RepoRef,
    ReviewEvent,
    ensure_marker,
    replace_marked_block,
)
from app.platforms.diff import build_file_diff
from app.platforms.gitlab.client import gitlab_client
from app.platforms.gitlab.finishing import GitLabFinishingMixin
from app.platforms.gitlab.issues import GitLabIssuesMixin
from app.platforms.gitlab.workspace import GitLabWorkspaceMixin

log = get_logger(__name__)

STATUS_NAME = "HootPR"
# GitLab commit statuses have no "neutral": map it to "skipped" (plan decision P10).
_STATE: dict[CheckState, str] = {
    "queued": "pending",
    "in_progress": "running",
    "success": "success",
    "failure": "failed",
    "neutral": "skipped",
}
_PR_STATE: dict[str, PrState] = {"opened": "open", "merged": "merged"}
_EMOJI = {
    "+1": "thumbsup",
    "-1": "thumbsdown",
    "eyes": "eyes",
    "rocket": "rocket",
    "heart": "heart",
    "hooray": "tada",
    "laugh": "laughing",
    "confused": "confused",
}


def _dt(v: Any) -> datetime | None:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None


def _file(d: dict[str, Any]) -> FileDiff:
    status: FileStatus
    if d.get("new_file"):
        status = "added"
    elif d.get("deleted_file"):
        status = "removed"
    elif d.get("renamed_file"):
        status = "renamed"
    else:
        status = "modified"
    old = str(d["old_path"]) if d.get("renamed_file") and d.get("old_path") else None
    return build_file_diff(str(d["new_path"]), d.get("diff") or None, status, old)


def gitlab_suggestion(body: str, suggestion: str | None, start: int | None, end: int) -> str:
    """GitLab multi-line suggestions: ``suggestion:-N+0`` replaces N lines above the anchor."""
    if suggestion is None:
        return body
    above = (end - start) if start is not None and start < end else 0
    return f"{body}\n\n```suggestion:-{above}+0\n{suggestion}\n```"


DEVELOPER_ACCESS = 30


def _changes_count(raw: object) -> int | None:
    """``changes_count`` of a merge request ("12", "1000+", None) as an int."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(0, raw)
    if isinstance(raw, str):
        digits = raw.strip().rstrip("+")
        if digits.isdigit():
            return int(digits)
    return None


class GitLabPlatform(GitLabFinishingMixin, GitLabIssuesMixin, GitLabWorkspaceMixin):
    provider: ProviderName = "gitlab"

    def __init__(
        self, token: str, *, base_url: str = "https://gitlab.com", bot_user_id: int | None = None
    ) -> None:
        self._token = token
        # The bot user behind the token: only its notes are ever edited (looked up lazily).
        self._bot_user_id = bot_user_id
        self._web = base_url.rstrip("/")
        self._http = gitlab_client(base_url, token)

    @staticmethod
    def _p(repo: RepoRef) -> str:
        return f"/projects/{repo.provider_repo_id}"

    def close(self) -> None:
        self._http.close()

    def _bot_id(self) -> int:
        if self._bot_user_id is None:
            self._bot_user_id = int(self._http.get_json("/user")["id"])
        return self._bot_user_id

    def can_write(self, repo: RepoRef, username: str) -> bool:
        """Developer (30) or higher, including inherited group membership."""
        members = self._http.get_json(
            f"{self._p(repo)}/members/all", params={"query": username, "per_page": 100}
        )
        want = username.lower()
        return any(
            str(m.get("username") or "").lower() == want
            and int(m.get("access_level") or 0) >= DEVELOPER_ACCESS
            for m in members or []
        )

    def _mr(self, repo: RepoRef, number: int) -> dict[str, Any]:
        data: dict[str, Any] = self._http.get_json(f"{self._p(repo)}/merge_requests/{number}")
        return data

    # --- read
    def get_pull_request(self, repo: RepoRef, number: int) -> PullRequest:
        d = self._mr(repo, number)
        refs = d.get("diff_refs") or {}
        return PullRequest(
            number=int(d["iid"]),
            title=str(d["title"]),
            body=str(d.get("description") or ""),
            author_username=str(d["author"]["username"]),
            state=_PR_STATE.get(str(d["state"]), "closed"),
            is_draft=bool(d.get("draft") or d.get("work_in_progress")),
            base_ref=str(d["target_branch"]),
            head_ref=str(d["source_branch"]),
            base_sha=str(refs.get("base_sha") or ""),
            head_sha=str(refs.get("head_sha") or d.get("sha") or ""),
            labels=tuple(str(x) for x in d.get("labels", [])),
            url=str(d["web_url"]),
            # The MR API has no line counts (they would need the paginated /diffs call);
            # ``changes_count`` is a string, "1000+" past GitLab's limit. Sizes the review hold.
            changed_files=_changes_count(d.get("changes_count")),
        )

    def get_diff(
        self,
        repo: RepoRef,
        number: int,
        base_sha: str | None = None,
        head_sha: str | None = None,
    ) -> list[FileDiff]:
        if base_sha and head_sha:
            d = self._http.get_json(
                f"{self._p(repo)}/repository/compare",
                params={"from": base_sha, "to": head_sha, "straight": "false"},
            )
            return [_file(x) for x in d.get("diffs", [])]
        return [
            _file(x) for x in self._http.paginate(f"{self._p(repo)}/merge_requests/{number}/diffs")
        ]

    def get_file(self, repo: RepoRef, path: str, ref: str) -> str | None:
        try:
            return self._http.request(
                "GET",
                f"{self._p(repo)}/repository/files/{quote(path, safe='')}/raw",
                params={"ref": ref},
            ).text
        except NotFoundError:
            return None

    def list_comments(self, repo: RepoRef, number: int) -> list[Comment]:
        out: list[Comment] = []
        for disc in self._http.paginate(f"{self._p(repo)}/merge_requests/{number}/discussions"):
            for n in disc.get("notes", []):
                if n.get("system"):
                    continue
                pos = n.get("position") or {}
                line = pos.get("new_line")
                out.append(
                    Comment(
                        str(n["id"]),
                        str(n["author"]["username"]),
                        str(n.get("body") or ""),
                        _dt(n.get("created_at")),
                        path=str(pos["new_path"]) if pos.get("new_path") else None,
                        line=int(line) if line is not None else None,
                        thread_ref=str(disc["id"]),
                        resolved=bool(n.get("resolved")) if n.get("resolvable") else None,
                    )
                )
        return out

    def clone_credentials(self, repo: RepoRef) -> CloneCredentials:
        return CloneCredentials(
            url=f"{self._web}/{repo.full_name}.git", username="oauth2", token=self._token
        )

    # --- write
    def post_review(
        self,
        repo: RepoRef,
        number: int,
        head_sha: str,
        summary: str | None,
        comments: list[InlineComment],
        event: ReviewEvent = "COMMENT",
    ) -> list[str]:
        """One positioned MR discussion per inline comment, then an optional summary note.

        GitLab has no review verdict: ``APPROVE`` also approves the MR and ``REQUEST_CHANGES``
        also unapproves it (both best effort; the commit status carries the verdict).
        A discussion GitLab rejects (400/422, e.g. a line outside the diff) yields ``""``."""
        ids: list[str] = []
        base = f"{self._p(repo)}/merge_requests/{number}"
        if comments:
            refs = self._mr(repo, number)["diff_refs"]
            for c in comments:
                position: dict[str, Any] = {
                    "position_type": "text",
                    "base_sha": refs["base_sha"],
                    "start_sha": refs["start_sha"],
                    "head_sha": refs["head_sha"],
                    "new_path": c.path,
                    "old_path": c.old_path or c.path,
                }
                if c.side == "LEFT":
                    position["old_line"] = c.end_line
                else:
                    position["new_line"] = c.end_line
                    if c.old_line is not None:  # unchanged line: GitLab needs both sides
                        position["old_line"] = c.old_line
                try:
                    d = self._http.request(
                        "POST",
                        f"{base}/discussions",
                        json={
                            "body": gitlab_suggestion(
                                c.body, c.suggestion, c.start_line, c.end_line
                            ),
                            "position": position,
                        },
                    ).json()
                except PlatformError as exc:
                    if exc.status_code not in (400, 422):
                        raise
                    ids.append("")
                    continue
                ids.append(str(d["id"]))
        if summary:
            self._http.request("POST", f"{base}/notes", json={"body": summary})
        if event == "APPROVE":
            self._best_effort("POST", f"{base}/approve")
        elif event == "REQUEST_CHANGES":
            self._best_effort("POST", f"{base}/unapprove")
        return ids

    def _best_effort(self, method: str, path: str) -> None:
        try:
            self._http.request(method, path)
        except PlatformError as exc:
            if exc.status_code not in (401, 403, 404, 405):
                raise
            log.info("gitlab_approval_skipped", path=path, status=exc.status_code)

    def upsert_comment(self, repo: RepoRef, number: int, marker: str, body: str) -> str:
        body = ensure_marker(body, marker)
        base = f"{self._p(repo)}/merge_requests/{number}/notes"
        bot_id = self._bot_id()
        for n in self._http.paginate(base, {"sort": "asc"}):
            author_id = (n.get("author") or {}).get("id")
            if (
                not n.get("system")
                and author_id is not None
                and int(author_id) == bot_id
                and marker in str(n.get("body") or "")
            ):
                self._http.request("PUT", f"{base}/{n['id']}", json={"body": body})
                return str(n["id"])
        return str(self._http.request("POST", base, json={"body": body}).json()["id"])

    def reply_to_comment(self, repo: RepoRef, number: int, thread_ref: str, body: str) -> str:
        d = self._http.request(
            "POST",
            f"{self._p(repo)}/merge_requests/{number}/discussions/{thread_ref}/notes",
            json={"body": body},
        ).json()
        return str(d["id"])

    def update_pr_description(
        self, repo: RepoRef, number: int, marker: str, block: str, placeholder: str | None = None
    ) -> None:
        current = str(self._mr(repo, number).get("description") or "")
        self._http.request(
            "PUT",
            f"{self._p(repo)}/merge_requests/{number}",
            json={"description": replace_marked_block(current, marker, block, placeholder)},
        )

    def update_pr_title(self, repo: RepoRef, number: int, title: str) -> None:
        self._http.request("PUT", f"{self._p(repo)}/merge_requests/{number}", json={"title": title})

    def set_status(
        self, repo: RepoRef, sha: str, state: CheckState, title: str, summary: str
    ) -> None:
        self._http.request(
            "POST",
            f"{self._p(repo)}/statuses/{sha}",
            json={"state": _STATE[state], "name": STATUS_NAME, "description": title[:255]},
        )

    def resolve_thread(self, repo: RepoRef, number: int, thread_ref: str) -> None:
        self._http.request(
            "PUT",
            f"{self._p(repo)}/merge_requests/{number}/discussions/{thread_ref}",
            params={"resolved": "true"},
        )

    def add_reaction(self, repo: RepoRef, comment_ref: str, emoji: str) -> None:
        """``comment_ref`` is ``"<mr_iid>:<note_id>"`` (award emoji is scoped to the MR)."""
        iid, note_id = comment_ref.split(":", 1)
        self._http.request(
            "POST",
            f"{self._p(repo)}/merge_requests/{iid}/notes/{note_id}/award_emoji",
            json={"name": _EMOJI.get(emoji, "eyes")},
        )


if TYPE_CHECKING:
    _conforms: GitPlatform = GitLabPlatform.__new__(GitLabPlatform)
