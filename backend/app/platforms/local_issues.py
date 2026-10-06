"""In-memory Phase 5 issue methods for ``LocalPlatform`` (tests, e2e, evals)."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from app.platforms.base import NotFoundError, RepoRef
from app.platforms.issues import Issue


class LocalIssuesMixin:
    """State is created lazily so ``LocalPlatform.__init__`` needs no changes.

    Issues are keyed by ``(repo full_name, number)`` so foreign-repo references work too."""

    @property
    def issues(self) -> dict[tuple[str, int], Issue]:
        store: dict[tuple[str, int], Issue] | None = self.__dict__.get("_issues")
        if store is None:
            store = self.__dict__["_issues"] = {}
        return store

    @property
    def issue_comments(self) -> list[tuple[str, int, str]]:
        """(repo full_name, issue number, body) for every issue comment posted."""
        out: list[tuple[str, int, str]] | None = self.__dict__.get("_issue_comments")
        if out is None:
            out = self.__dict__["_issue_comments"] = []
        return out

    @property
    def labels_added(self) -> list[tuple[str, int, tuple[str, ...]]]:
        out: list[tuple[str, int, tuple[str, ...]]] | None = self.__dict__.get("_labels_added")
        if out is None:
            out = self.__dict__["_labels_added"] = []
        return out

    @property
    def repo_labels(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] | None = self.__dict__.get("_repo_labels")
        if out is None:
            out = self.__dict__["_repo_labels"] = {}
        return out

    @property
    def committers(self) -> dict[str, list[str]]:
        """``path`` (or ``""`` for the whole repo) -> recent committer usernames."""
        out: dict[str, list[str]] | None = self.__dict__.get("_committers")
        if out is None:
            out = self.__dict__["_committers"] = {}
        return out

    def _issue_number(self, full_name: str) -> int:
        counter = self.__dict__.get("_issue_ids")
        if counter is None:
            counter = self.__dict__["_issue_ids"] = itertools.count(1000)
        n = int(next(counter))
        while (full_name, n) in self.issues:
            n = int(next(counter))
        return n

    # --- test helper
    def add_issue(self, repo: RepoRef | str, issue: Issue) -> None:
        name = repo if isinstance(repo, str) else repo.full_name
        self.issues[(name, issue.number)] = issue

    # --- GitPlatform
    def get_issue(self, repo: RepoRef, number: int) -> Issue:
        issue = self.issues.get((repo.full_name, number))
        if issue is None:
            raise NotFoundError(404, f"issue {repo.full_name}#{number} not found")
        return issue

    def create_issue(
        self, repo: RepoRef, title: str, body: str, labels: Sequence[str] = ()
    ) -> Issue:
        n = self._issue_number(repo.full_name)
        issue = Issue(
            n, title, body, "open", "hootpr[bot]", tuple(labels),
            f"https://local/{repo.full_name}/issues/{n}", repo.full_name,
        )  # fmt: skip
        self.issues[(repo.full_name, n)] = issue
        return issue

    def comment_on_issue(self, repo: RepoRef, number: int, body: str) -> str:
        self.issue_comments.append((repo.full_name, number, body))
        return f"issue-note-{len(self.issue_comments)}"

    def add_labels(
        self, repo: RepoRef, number: int, labels: Sequence[str], *, merge_request: bool = False
    ) -> None:
        if labels:
            self.labels_added.append((repo.full_name, number, tuple(labels)))

    def list_labels(self, repo: RepoRef) -> list[str]:
        return list(self.repo_labels.get(repo.full_name, []))

    def recent_committers(
        self, repo: RepoRef, path: str | None = None, limit: int = 10
    ) -> list[str]:
        return list(self.committers.get(path or "", []))[:limit]
