"""In-memory GitPlatform for tests, e2e and (Phase 2) evals. Nothing leaves the process."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.platforms.base import (
    CheckState,
    CloneCredentials,
    Comment,
    FileDiff,
    GitPlatform,
    InlineComment,
    NotFoundError,
    PlatformError,
    ProviderName,
    PullRequest,
    RepoRef,
    ReviewEvent,
    ensure_marker,
    replace_marked_block,
)
from app.platforms.local_finishing import LocalFinishingMixin
from app.platforms.local_issues import LocalIssuesMixin
from app.platforms.local_workspace import LocalWorkspaceMixin

BOT_USERNAME = "hootpr[bot]"


@dataclass(frozen=True)
class StatusRecord:
    repo_id: str
    sha: str
    state: CheckState
    title: str
    summary: str


@dataclass(frozen=True)
class PostedReview:
    repo_id: str
    number: int
    head_sha: str
    summary: str | None
    comments: list[InlineComment] = field(default_factory=list)  # only the posted ones
    event: str = "COMMENT"


class LocalPlatform(LocalFinishingMixin, LocalIssuesMixin, LocalWorkspaceMixin):
    def __init__(self, provider: ProviderName = "github") -> None:
        self.provider: ProviderName = provider
        self.prs: dict[tuple[str, int], PullRequest] = {}
        self.diffs: dict[tuple[str, int], list[FileDiff]] = {}
        self.files: dict[tuple[str, str, str], str] = {}
        self.comments: dict[tuple[str, int], list[Comment]] = {}
        self.inline_comments: dict[tuple[str, int], list[Comment]] = {}
        self.descriptions: dict[tuple[str, int], str] = {}
        self.statuses: list[StatusRecord] = []
        self.reviews: list[PostedReview] = []
        # Usernames without write access (everyone else can write).
        self.readers: set[str] = set()
        self.permission_error: Exception | None = None
        self.resolved: list[str] = []
        self.reactions: list[tuple[str, str]] = []
        self.titles: dict[tuple[str, int], str] = {}
        self.approvals: list[tuple[str, int]] = []
        self.fail_next: Exception | None = None
        # Phase 2: a real checkout per repo (clone source for the sandbox) and anchors the
        # simulated provider rejects (GitHub: whole review 422; GitLab: that comment only).
        self.repo_paths: dict[str, Path] = {}
        self.invalid_anchors: set[tuple[str, int]] = set()
        self._ids = itertools.count(1)

    # --- test helpers
    def add_pull_request(self, repo: RepoRef, pr: PullRequest, diff: list[FileDiff]) -> None:
        key = (repo.provider_repo_id, pr.number)
        self.prs[key] = pr
        self.diffs[key] = list(diff)
        self.descriptions[key] = pr.body
        self.comments.setdefault(key, [])
        self.inline_comments.setdefault(key, [])

    def register_repo_path(self, repo: RepoRef, path: Path) -> None:
        self.repo_paths[repo.provider_repo_id] = path

    def set_file(self, repo: RepoRef, path: str, ref: str, content: str) -> None:
        self.files[(repo.provider_repo_id, path, ref)] = content

    def _key(self, repo: RepoRef, number: int) -> tuple[str, int]:
        key = (repo.provider_repo_id, number)
        if key not in self.prs:
            raise NotFoundError(404, f"PR {repo.full_name}#{number} not found")
        return key

    def _maybe_fail(self) -> None:
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc

    def _new_id(self) -> str:
        return str(next(self._ids))

    # --- read
    def get_pull_request(self, repo: RepoRef, number: int) -> PullRequest:
        key = self._key(repo, number)
        pr = replace(self.prs[key], body=self.descriptions[key])
        return replace(pr, title=self.titles[key]) if key in self.titles else pr

    def get_diff(
        self,
        repo: RepoRef,
        number: int,
        base_sha: str | None = None,
        head_sha: str | None = None,
    ) -> list[FileDiff]:
        return list(self.diffs[self._key(repo, number)])

    def get_file(self, repo: RepoRef, path: str, ref: str) -> str | None:
        return self.files.get((repo.provider_repo_id, path, ref))

    def list_comments(self, repo: RepoRef, number: int) -> list[Comment]:
        key = self._key(repo, number)
        inline = [
            replace(c, resolved=c.thread_ref in self.resolved) for c in self.inline_comments[key]
        ]
        return [*self.comments[key], *inline]

    def clone_credentials(self, repo: RepoRef) -> CloneCredentials:
        path = self.repo_paths.get(repo.provider_repo_id)
        url = f"file://{path}" if path else f"file:///local/{repo.full_name}.git"
        return CloneCredentials(url=url, username="local", token="")

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
        self._maybe_fail()
        self._key(repo, number)
        bad = [(c.path, c.end_line) in self.invalid_anchors for c in comments]
        if self.provider == "github" and any(bad):
            raise PlatformError(
                422,
                "Unprocessable Entity: pull_request_review_thread.line must be part of the diff",
            )
        posted = [c for c, rejected in zip(comments, bad, strict=True) if not rejected]
        self.reviews.append(
            PostedReview(repo.provider_repo_id, number, head_sha, summary, posted, event)
        )
        if event == "APPROVE":
            self.approvals.append((repo.provider_repo_id, number))
        ids = ["" if rejected else self._new_id() for rejected in bad]
        key = self._key(repo, number)
        for c, cid in zip(comments, ids, strict=True):
            if cid:  # inline comments are listed like GitHub's pulls/{n}/comments
                self.inline_comments[key].append(
                    Comment(
                        cid,
                        BOT_USERNAME,
                        c.body,
                        datetime.now(UTC),
                        path=c.path,
                        line=c.end_line,
                        thread_ref=cid,
                    )
                )
        return ids

    def upsert_comment(self, repo: RepoRef, number: int, marker: str, body: str) -> str:
        self._maybe_fail()
        key = self._key(repo, number)
        body = ensure_marker(body, marker)
        for i, c in enumerate(self.comments[key]):
            if marker in c.body:
                self.comments[key][i] = replace(c, body=body)
                return c.id
        cid = self._new_id()
        self.comments[key].append(Comment(cid, BOT_USERNAME, body, datetime.now(UTC)))
        return cid

    def reply_to_comment(self, repo: RepoRef, number: int, thread_ref: str, body: str) -> str:
        self._maybe_fail()
        key = self._key(repo, number)
        cid = self._new_id()
        self.comments[key].append(
            Comment(cid, BOT_USERNAME, body, datetime.now(UTC), thread_ref=thread_ref)
        )
        return cid

    def update_pr_description(
        self, repo: RepoRef, number: int, marker: str, block: str, placeholder: str | None = None
    ) -> None:
        self._maybe_fail()
        key = self._key(repo, number)
        self.descriptions[key] = replace_marked_block(
            self.descriptions[key], marker, block, placeholder
        )

    def update_pr_title(self, repo: RepoRef, number: int, title: str) -> None:
        self._maybe_fail()
        self.titles[self._key(repo, number)] = title

    def set_status(
        self, repo: RepoRef, sha: str, state: CheckState, title: str, summary: str
    ) -> None:
        self._maybe_fail()
        self.statuses.append(StatusRecord(repo.provider_repo_id, sha, state, title, summary))

    def can_write(self, repo: RepoRef, username: str) -> bool:
        if self.permission_error is not None:
            raise self.permission_error
        return username not in self.readers

    def resolve_thread(self, repo: RepoRef, number: int, thread_ref: str) -> None:
        self._maybe_fail()
        self.resolved.append(thread_ref)

    def add_reaction(self, repo: RepoRef, comment_ref: str, emoji: str) -> None:
        self._maybe_fail()
        self.reactions.append((comment_ref, emoji))


if TYPE_CHECKING:
    _conforms: GitPlatform = LocalPlatform()
