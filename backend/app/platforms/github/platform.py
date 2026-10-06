"""GitHubPlatform: GitPlatform over the GitHub REST API with an installation token."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from app.platforms.base import (
    CheckState,
    CloneCredentials,
    Comment,
    FileDiff,
    FileStatus,
    GitPlatform,
    InlineComment,
    NotFoundError,
    ProviderName,
    PrState,
    PullRequest,
    RepoRef,
    ReviewEvent,
    ensure_marker,
    replace_marked_block,
)
from app.platforms.diff import build_file_diff
from app.platforms.github.app_auth import GitHubAppAuth
from app.platforms.github.finishing import GitHubFinishingMixin
from app.platforms.github.issues import GitHubIssuesMixin
from app.platforms.github.workspace import GitHubWorkspaceMixin

CHECK_NAME = "HootPR"
_STATUS: dict[str, FileStatus] = {"added": "added", "removed": "removed", "renamed": "renamed"}
_WRITE_PERMS = frozenset({"admin", "maintain", "write"})
_REACTIONS = frozenset({"+1", "-1", "laugh", "confused", "heart", "hooray", "rocket", "eyes"})
_RESOLVE = (
    "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) "
    "{ thread { id isResolved } } }"
)
_THREADS = (
    "query($owner: String!, $name: String!, $number: Int!, $after: String) {"
    " repository(owner: $owner, name: $name) { pullRequest(number: $number) {"
    " reviewThreads(first: 100, after: $after) { pageInfo { hasNextPage endCursor }"
    " nodes { id isResolved comments(first: 1) { nodes { databaseId } } } } } } }"
)


def _dt(v: Any) -> datetime | None:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None


def _file(f: dict[str, Any]) -> FileDiff:
    status = _STATUS.get(str(f.get("status")), "modified")
    old = f.get("previous_filename")
    return build_file_diff(
        str(f["filename"]), f.get("patch") or None, status, str(old) if old else None
    )


def suggestion_body(body: str, suggestion: str | None) -> str:
    return body if suggestion is None else f"{body}\n\n```suggestion\n{suggestion}\n```"


def _size(d: dict[str, Any], *keys: str) -> int | None:
    """Sum of integer PR size fields; None when any is missing (list endpoints omit them)."""
    vals = [d.get(k) for k in keys]
    if any(not isinstance(v, int) or isinstance(v, bool) for v in vals):
        return None
    return sum(int(v) for v in vals if isinstance(v, int))


def _pr_state(d: dict[str, Any]) -> PrState:
    if d.get("merged_at"):
        return "merged"
    return "open" if d.get("state") == "open" else "closed"


class GitHubPlatform(GitHubFinishingMixin, GitHubIssuesMixin, GitHubWorkspaceMixin):
    provider: ProviderName = "github"

    def __init__(
        self,
        auth: GitHubAppAuth,
        installation_id: int,
        *,
        web_url: str = "https://github.com",
        bot_login: str = "hootpr[bot]",
    ) -> None:
        self._auth = auth
        # The App's bot account (``<slug>[bot]``): only its comments are ever edited.
        self._bot_login = bot_login.lower()
        self._iid = installation_id
        self._http = auth.installation_client(installation_id)
        self._web = web_url.rstrip("/")
        # (repo, number) -> thread map, reused by resolve_thread for this instance's lifetime.
        self._thread_cache: dict[tuple[str, int], dict[str, tuple[str, bool]]] = {}

    @staticmethod
    def _r(repo: RepoRef) -> str:
        return f"/repos/{repo.full_name}"

    def close(self) -> None:
        self._http.close()

    # --- read
    def get_pull_request(self, repo: RepoRef, number: int) -> PullRequest:
        d = self._http.get_json(f"{self._r(repo)}/pulls/{number}")
        return PullRequest(
            number=int(d["number"]),
            title=str(d["title"]),
            body=str(d.get("body") or ""),
            author_username=str(d["user"]["login"]),
            state=_pr_state(d),
            is_draft=bool(d.get("draft")),
            base_ref=str(d["base"]["ref"]),
            head_ref=str(d["head"]["ref"]),
            base_sha=str(d["base"]["sha"]),
            head_sha=str(d["head"]["sha"]),
            labels=tuple(str(lb["name"]) for lb in d.get("labels", [])),
            url=str(d["html_url"]),
            changed_lines=_size(d, "additions", "deletions"),
            changed_files=_size(d, "changed_files"),
        )

    def get_diff(
        self,
        repo: RepoRef,
        number: int,
        base_sha: str | None = None,
        head_sha: str | None = None,
    ) -> list[FileDiff]:
        if base_sha and head_sha:
            d = self._http.get_json(f"{self._r(repo)}/compare/{base_sha}...{head_sha}")
            return [_file(f) for f in d.get("files", [])]
        return [_file(f) for f in self._http.paginate(f"{self._r(repo)}/pulls/{number}/files")]

    def get_file(self, repo: RepoRef, path: str, ref: str) -> str | None:
        try:
            resp = self._http.request(
                "GET",
                f"{self._r(repo)}/contents/{path}",
                params={"ref": ref},
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        except NotFoundError:
            return None
        return resp.text

    def list_comments(self, repo: RepoRef, number: int) -> list[Comment]:
        out = [
            Comment(
                str(c["id"]),
                str(c["user"]["login"]),
                str(c.get("body") or ""),
                _dt(c.get("created_at")),
            )
            for c in self._http.paginate(f"{self._r(repo)}/issues/{number}/comments")
        ]
        review = list(self._http.paginate(f"{self._r(repo)}/pulls/{number}/comments"))
        threads = self._threads(repo, number) if review else {}
        for c in review:
            line = c.get("line")
            thread_ref = str(c.get("in_reply_to_id") or c["id"])
            out.append(
                Comment(
                    str(c["id"]),
                    str(c["user"]["login"]),
                    str(c.get("body") or ""),
                    _dt(c.get("created_at")),
                    path=str(c["path"]) if c.get("path") else None,
                    line=int(line) if line is not None else None,
                    thread_ref=thread_ref,
                    resolved=threads.get(thread_ref, ("", False))[1],
                )
            )
        return out

    def _threads(self, repo: RepoRef, number: int) -> dict[str, tuple[str, bool]]:
        """Root review-comment id -> (thread node id, isResolved)."""
        owner, name = repo.full_name.split("/", 1)
        out: dict[str, tuple[str, bool]] = {}
        after: str | None = None
        while True:
            data = self._http.request(
                "POST",
                "/graphql",
                json={
                    "query": _THREADS,
                    "variables": {"owner": owner, "name": name, "number": number, "after": after},
                },
            ).json()
            threads = ((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
            page = threads.get("reviewThreads") or {}
            for node in page.get("nodes") or []:
                roots = (node.get("comments") or {}).get("nodes") or []
                if roots:
                    out[str(roots[0]["databaseId"])] = (str(node["id"]), bool(node["isResolved"]))
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return out
            after = info.get("endCursor")

    def can_write(self, repo: RepoRef, username: str) -> bool:
        try:
            d = self._http.get_json(
                f"{self._r(repo)}/collaborators/{quote(username, safe='')}/permission"
            )
        except NotFoundError:
            return False
        role = str(d.get("role_name") or "")
        return str(d.get("permission") or "") in _WRITE_PERMS or role in _WRITE_PERMS

    def clone_credentials(self, repo: RepoRef) -> CloneCredentials:
        return CloneCredentials(
            url=f"{self._web}/{repo.full_name}.git",
            username="x-access-token",
            token=self._auth.installation_token(self._iid),
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
        """All inline comments go out as ONE review (one notification, like CodeRabbit)."""
        if not comments and not summary:
            return []
        payload: list[dict[str, Any]] = []
        for c in comments:
            item: dict[str, Any] = {"path": c.path, "line": c.end_line, "side": c.side}
            if c.start_line is not None and c.start_line < c.end_line:
                item["start_line"] = c.start_line
                item["start_side"] = c.side
            item["body"] = suggestion_body(c.body, c.suggestion)
            payload.append(item)
        review = self._http.request(
            "POST",
            f"{self._r(repo)}/pulls/{number}/reviews",
            json={
                "commit_id": head_sha,
                "event": event,
                "body": summary or "",
                "comments": payload,
            },
        ).json()
        if not comments:
            return []
        posted = self._http.paginate(
            f"{self._r(repo)}/pulls/{number}/reviews/{review['id']}/comments"
        )
        return [str(c["id"]) for c in posted]

    def upsert_comment(self, repo: RepoRef, number: int, marker: str, body: str) -> str:
        body = ensure_marker(body, marker)
        for c in self._http.paginate(f"{self._r(repo)}/issues/{number}/comments"):
            author = str((c.get("user") or {}).get("login") or "").lower()
            if author == self._bot_login and marker in str(c.get("body") or ""):
                self._http.request(
                    "PATCH", f"{self._r(repo)}/issues/comments/{c['id']}", json={"body": body}
                )
                return str(c["id"])
        created = self._http.request(
            "POST", f"{self._r(repo)}/issues/{number}/comments", json={"body": body}
        ).json()
        return str(created["id"])

    def reply_to_comment(self, repo: RepoRef, number: int, thread_ref: str, body: str) -> str:
        d = self._http.request(
            "POST",
            f"{self._r(repo)}/pulls/{number}/comments/{thread_ref}/replies",
            json={"body": body},
        ).json()
        return str(d["id"])

    def update_pr_description(
        self, repo: RepoRef, number: int, marker: str, block: str, placeholder: str | None = None
    ) -> None:
        current = self.get_pull_request(repo, number).body
        self._http.request(
            "PATCH",
            f"{self._r(repo)}/pulls/{number}",
            json={"body": replace_marked_block(current, marker, block, placeholder)},
        )

    def update_pr_title(self, repo: RepoRef, number: int, title: str) -> None:
        self._http.request("PATCH", f"{self._r(repo)}/pulls/{number}", json={"title": title})

    def set_status(
        self, repo: RepoRef, sha: str, state: CheckState, title: str, summary: str
    ) -> None:
        """Each call creates a new check run; GitHub shows the latest one per name."""
        body: dict[str, Any] = {
            "name": CHECK_NAME,
            "head_sha": sha,
            "output": {"title": title[:255], "summary": summary[:65000]},
        }
        if state in ("queued", "in_progress"):
            body["status"] = state
        else:
            body["status"] = "completed"
            body["conclusion"] = state
        self._http.request("POST", f"{self._r(repo)}/check-runs", json=body)

    def resolve_thread(self, repo: RepoRef, number: int, thread_ref: str) -> None:
        """``thread_ref`` is the thread's root review-comment id (or a ``PRRT_…`` node id)."""
        node = (
            thread_ref
            if thread_ref.startswith("PRRT_")
            else self._thread_node(repo, number, thread_ref)
        )
        if not node:
            raise NotFoundError(404, f"review thread {thread_ref} not found")
        self._http.request("POST", "/graphql", json={"query": _RESOLVE, "variables": {"id": node}})

    def _thread_node(self, repo: RepoRef, number: int, thread_ref: str) -> str:
        """Node id of a thread by root comment id. The paginated listing is fetched once per
        platform instance (``@hootpr resolve`` resolves many threads) and refetched on a miss."""
        key = (repo.provider_repo_id, number)
        cached = self._thread_cache.get(key)
        if cached is not None and thread_ref in cached:
            return cached[thread_ref][0]
        fresh = self._threads(repo, number)
        self._thread_cache[key] = fresh
        return fresh.get(thread_ref, ("", False))[0]

    def add_reaction(self, repo: RepoRef, comment_ref: str, emoji: str) -> None:
        """``comment_ref``: an issue-comment id, or ``"review:<id>"`` for a review comment."""
        content = emoji if emoji in _REACTIONS else "eyes"
        if comment_ref.startswith("review:"):
            path = f"{self._r(repo)}/pulls/comments/{comment_ref.removeprefix('review:')}/reactions"
        else:
            path = f"{self._r(repo)}/issues/comments/{comment_ref}/reactions"
        self._http.request("POST", path, json={"content": content})


if TYPE_CHECKING:
    _conforms: GitPlatform = GitHubPlatform.__new__(GitHubPlatform)
