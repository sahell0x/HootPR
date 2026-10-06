"""LocalPlatform side of Change Stack actions (tests / evals)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from app.platforms.base import PlatformError, RepoRef, ReviewEvent
from app.platforms.workspace import MergeMethod, MergeResult, UserReviewComment


@dataclass(frozen=True)
class UserReview:
    repo_id: str
    number: int
    head_sha: str
    event: str
    body: str
    comments: tuple[UserReviewComment, ...]


@dataclass
class LocalWorkspaceState:
    user_reviews: list[UserReview] = field(default_factory=list)
    merges: list[tuple[str, int, str]] = field(default_factory=list)
    unmergeable: set[tuple[str, int]] = field(default_factory=set)


class LocalWorkspaceMixin:
    @property
    def workspace(self) -> LocalWorkspaceState:
        state = self.__dict__.get("_workspace_state")
        if state is None:
            state = LocalWorkspaceState()
            self.__dict__["_workspace_state"] = state
        return state

    def submit_review(
        self,
        repo: RepoRef,
        number: int,
        head_sha: str,
        event: ReviewEvent,
        body: str,
        comments: Sequence[UserReviewComment] = (),
    ) -> str:
        ws = self.workspace
        ws.user_reviews.append(
            UserReview(repo.provider_repo_id, number, head_sha, event, body, tuple(comments))
        )
        return f"user-review-{len(ws.user_reviews)}"

    def merge_pull_request(
        self,
        repo: RepoRef,
        number: int,
        *,
        method: MergeMethod = "merge",
        sha: str | None = None,
        commit_title: str | None = None,
    ) -> MergeResult:
        key = (repo.provider_repo_id, number)
        if key in self.workspace.unmergeable:
            return MergeResult(merged=False, sha=None, message="not mergeable")
        prs = getattr(self, "prs", {})
        pr = prs.get(key)
        if pr is None:
            raise PlatformError(404, "pull request not found")
        if sha and pr.head_sha != sha:
            return MergeResult(merged=False, sha=None, message="head changed")
        prs[key] = replace(pr, state="merged")
        self.workspace.merges.append((repo.provider_repo_id, number, method))
        return MergeResult(merged=True, sha=f"merge-{number}", message="merged")
