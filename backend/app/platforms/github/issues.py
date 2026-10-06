"""GitHub side of Phase 5: issues, labels, recent committers (spec §10.2).

A mixin of ``GitHubPlatform``. A ``RepoRef`` for another repository (a linked issue in
``owner/repo#12`` form) only needs ``full_name``: GitHub addresses repositories by name.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.platforms.base import NotFoundError, RepoRef
from app.platforms.http import HttpClient
from app.platforms.issues import Issue

MAX_LABELS = 200


def issue_from_json(d: dict[str, Any], full_name: str) -> Issue:
    return Issue(
        number=int(d["number"]),
        title=str(d.get("title") or ""),
        body=str(d.get("body") or ""),
        state="open" if d.get("state") == "open" else "closed",
        author_username=str((d.get("user") or {}).get("login") or ""),
        labels=tuple(
            str(lb["name"] if isinstance(lb, dict) else lb) for lb in d.get("labels") or []
        ),
        url=str(d.get("html_url") or ""),
        repo_full_name=full_name,
    )


class GitHubIssuesMixin:
    _http: HttpClient

    @staticmethod
    def _issues_path(repo: RepoRef) -> str:
        return f"/repos/{repo.full_name}/issues"

    def get_issue(self, repo: RepoRef, number: int) -> Issue:
        """Raises ``NotFoundError`` for a missing issue (or a PR number: GitHub serves PRs on the
        issues endpoint, so those are reported as not found too)."""
        d = self._http.get_json(f"{self._issues_path(repo)}/{number}")
        if d.get("pull_request"):
            raise NotFoundError(404, f"{repo.full_name}#{number} is a pull request")
        return issue_from_json(d, repo.full_name)

    def create_issue(
        self, repo: RepoRef, title: str, body: str, labels: Sequence[str] = ()
    ) -> Issue:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = list(labels)
        d = self._http.request("POST", self._issues_path(repo), json=payload).json()
        return issue_from_json(d, repo.full_name)

    def comment_on_issue(self, repo: RepoRef, number: int, body: str) -> str:
        d = self._http.request(
            "POST", f"{self._issues_path(repo)}/{number}/comments", json={"body": body}
        ).json()
        return str(d["id"])

    def add_labels(
        self, repo: RepoRef, number: int, labels: Sequence[str], *, merge_request: bool = False
    ) -> None:
        """Works for issues and pull requests alike (GitHub PRs are issues)."""
        if labels:
            self._http.request(
                "POST", f"{self._issues_path(repo)}/{number}/labels", json={"labels": list(labels)}
            )

    def list_labels(self, repo: RepoRef) -> list[str]:
        out: list[str] = []
        for lb in self._http.paginate(f"/repos/{repo.full_name}/labels", max_pages=2):
            out.append(str(lb["name"]))
            if len(out) >= MAX_LABELS:
                break
        return out

    def recent_committers(
        self, repo: RepoRef, path: str | None = None, limit: int = 10
    ) -> list[str]:
        """Logins of recent commit authors (of ``path`` when given), most recent first."""
        params: dict[str, Any] = {"per_page": min(100, max(limit * 3, 10))}
        if path:
            params["path"] = path
        data = self._http.get_json(f"/repos/{repo.full_name}/commits", params=params)
        out: list[str] = []
        for c in data or []:
            login = str((c.get("author") or {}).get("login") or "")
            if login and not login.endswith("[bot]") and login not in out:
                out.append(login)
            if len(out) >= limit:
                break
        return out
