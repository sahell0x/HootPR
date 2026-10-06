"""Provider-neutral types and the GitPlatform protocol (spec §4.1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from app.platforms.finishing import CiJobLog, FileChange
from app.platforms.issues import Issue
from app.platforms.workspace import MergeMethod, MergeResult, UserReviewComment

ProviderName = Literal["github", "gitlab"]
CheckState = Literal["queued", "in_progress", "success", "failure", "neutral"]
FileStatus = Literal["added", "modified", "removed", "renamed"]
Side = Literal["LEFT", "RIGHT"]
PrState = Literal["open", "closed", "merged"]
# Review verdict (request_changes_workflow, spec §7.7). GitLab maps APPROVE/REQUEST_CHANGES to
# best-effort approve/unapprove calls.
ReviewEvent = Literal["COMMENT", "REQUEST_CHANGES", "APPROVE"]


class PlatformError(Exception):
    """A provider API call failed (HTTP status is kept for callers that branch on it)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class NotFoundError(PlatformError):
    pass


@dataclass(frozen=True)
class RepoRef:
    provider: ProviderName
    provider_repo_id: str
    full_name: str


@dataclass(frozen=True)
class DiffLine:
    kind: Literal["context", "add", "del"]
    text: str
    old_line: int | None
    new_line: int | None


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True)
class FileDiff:
    path: str
    old_path: str | None
    status: FileStatus
    additions: int
    deletions: int
    patch: str | None
    hunks: tuple[Hunk, ...]
    is_binary: bool = False

    def changed_new_lines(self) -> set[int]:
        return {
            ln.new_line
            for h in self.hunks
            for ln in h.lines
            if ln.kind == "add" and ln.new_line is not None
        }


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    author_username: str
    state: PrState
    is_draft: bool
    base_ref: str
    head_ref: str
    base_sha: str
    head_sha: str
    labels: tuple[str, ...]
    url: str
    # PR size when the provider reports it (sizes the review's credit hold); None: unknown.
    changed_lines: int | None = None
    changed_files: int | None = None


@dataclass(frozen=True)
class Comment:
    id: str
    author_username: str
    body: str
    created_at: datetime | None
    path: str | None = None
    line: int | None = None
    thread_ref: str | None = None
    # Review-thread resolution state; ``None`` for comments that cannot be resolved.
    resolved: bool | None = None


@dataclass(frozen=True)
class InlineComment:
    path: str
    end_line: int
    body: str
    start_line: int | None = None
    side: Side = "RIGHT"
    suggestion: str | None = None
    # Old-side line of an unchanged (context) anchor line, and the pre-rename path. GitLab needs
    # both ``old_line`` and ``new_line`` to position a note on a context line.
    old_line: int | None = None
    old_path: str | None = None


@dataclass(frozen=True)
class CloneCredentials:
    url: str
    username: str
    token: str = field(repr=False)
    expires_at: datetime | None = None


class GitPlatform(Protocol):
    """Everything the pipeline needs from a git host (later-phase methods added later)."""

    provider: ProviderName

    # read
    def get_pull_request(self, repo: RepoRef, number: int) -> PullRequest: ...
    def get_diff(
        self,
        repo: RepoRef,
        number: int,
        base_sha: str | None = None,
        head_sha: str | None = None,
    ) -> list[FileDiff]: ...
    def get_file(self, repo: RepoRef, path: str, ref: str) -> str | None: ...
    def list_comments(self, repo: RepoRef, number: int) -> list[Comment]: ...
    def clone_credentials(self, repo: RepoRef) -> CloneCredentials: ...
    def can_write(self, repo: RepoRef, username: str) -> bool:
        """Whether ``username`` has write access (GitHub write/maintain/admin, GitLab
        Developer+). Unknown users are ``False``; API failures raise."""
        ...

    # write
    def post_review(
        self,
        repo: RepoRef,
        number: int,
        head_sha: str,
        summary: str | None,
        comments: list[InlineComment],
        event: ReviewEvent = "COMMENT",
    ) -> list[str]:
        """Post all inline comments (and ``summary``) as one review.

        Returns one id per comment; an empty string means that comment could not be posted
        (caller moves it to the walkthrough)."""
        ...

    def upsert_comment(self, repo: RepoRef, number: int, marker: str, body: str) -> str: ...
    def reply_to_comment(self, repo: RepoRef, number: int, thread_ref: str, body: str) -> str: ...
    def update_pr_description(
        self, repo: RepoRef, number: int, marker: str, block: str, placeholder: str | None = None
    ) -> None: ...
    def update_pr_title(self, repo: RepoRef, number: int, title: str) -> None: ...
    def set_status(
        self, repo: RepoRef, sha: str, state: CheckState, title: str, summary: str
    ) -> None: ...
    def resolve_thread(self, repo: RepoRef, number: int, thread_ref: str) -> None: ...
    def add_reaction(self, repo: RepoRef, comment_ref: str, emoji: str) -> None:
        """``comment_ref``: GitHub ``"<issue comment id>"`` or ``"review:<review comment id>"``;
        GitLab ``"<mr iid>:<note id>"``."""
        ...

    # Phase 4 (finishing touches, spec §10.1)
    def push_commit(
        self,
        repo: RepoRef,
        branch: str,
        parent_sha: str,
        message: str,
        changes: Sequence[FileChange],
        *,
        create_branch: bool = False,
        extra_parents: Sequence[str] = (),
        tree_base: str | None = None,
    ) -> str:
        """Commit ``changes`` (relative to ``tree_base``, default ``parent_sha``) on ``branch``.

        Without ``create_branch`` the branch must still point at ``parent_sha`` (fast-forward
        only, else ``PushRejected``). ``extra_parents`` make a merge commit. Returns the new
        commit sha."""
        ...

    def open_pull_request(
        self, repo: RepoRef, head: str, base: str, title: str, body: str
    ) -> PullRequest: ...

    def get_ci_logs(
        self,
        repo: RepoRef,
        sha: str,
        *,
        run_id: str | None = None,
        max_jobs: int = 5,
        max_log_kb: int = 32,
    ) -> list[CiJobLog]:
        """Failed CI jobs for ``sha`` (optionally one run/pipeline) with their log tails."""
        ...

    # Phase 5 (issues, spec §10.2)
    def get_issue(self, repo: RepoRef, number: int) -> Issue:
        """``repo`` may be a foreign repository (``provider_repo_id`` = its full path)."""
        ...

    def create_issue(
        self, repo: RepoRef, title: str, body: str, labels: Sequence[str] = ()
    ) -> Issue: ...
    def comment_on_issue(self, repo: RepoRef, number: int, body: str) -> str: ...
    def add_labels(
        self, repo: RepoRef, number: int, labels: Sequence[str], *, merge_request: bool = False
    ) -> None:
        """Label an issue, or (``merge_request=True``) the PR/MR with that number."""
        ...

    def list_labels(self, repo: RepoRef) -> list[str]: ...
    def recent_committers(
        self, repo: RepoRef, path: str | None = None, limit: int = 10
    ) -> list[str]:
        """Usernames of recent commit authors (of ``path`` when given), most recent first."""
        ...

    # Phase 8 (Change Stack, spec §10.5): called with the signed-in user's own OAuth token
    def submit_review(
        self,
        repo: RepoRef,
        number: int,
        head_sha: str,
        event: ReviewEvent,
        body: str,
        comments: Sequence[UserReviewComment] = (),
    ) -> str: ...

    def merge_pull_request(
        self,
        repo: RepoRef,
        number: int,
        *,
        method: MergeMethod = "merge",
        sha: str | None = None,
        commit_title: str | None = None,
    ) -> MergeResult: ...


def ensure_marker(body: str, marker: str) -> str:
    """Prefix ``body`` with ``marker`` unless it already contains it."""
    return body if marker in body else f"{marker}\n{body}"


def replace_marked_block(text: str, marker: str, block: str, placeholder: str | None = None) -> str:
    """Replace the ``<!-- marker:start -->…<!-- marker:end -->`` block in ``text``; else swap the
    first ``placeholder`` occurrence for it; else append it."""
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    wrapped = f"{start}\n{block}\n{end}"
    i = text.find(start)
    j = text.find(end, i + len(start)) if i != -1 else -1
    if i != -1 and j != -1:
        return text[:i] + wrapped + text[j + len(end) :]
    if placeholder and placeholder in text:
        return text.replace(placeholder, wrapped, 1)
    return f"{text}\n\n{wrapped}" if text else wrapped
