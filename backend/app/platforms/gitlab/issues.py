"""GitLab side of Phase 5: issues, labels, recent committers (spec §10.2).

A mixin of ``GitLabPlatform``. Projects are addressed by numeric id, or by the URL-encoded
``group/project`` path for a foreign project (a linked ``group/project#3`` issue).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.platforms.base import RepoRef
from app.platforms.http import HttpClient
from app.platforms.issues import Issue, gitlab_project_id

MAX_LABELS = 200


def issue_from_json(d: dict[str, Any], full_name: str) -> Issue:
    return Issue(
        number=int(d["iid"]),
        title=str(d.get("title") or ""),
        body=str(d.get("description") or ""),
        state="open" if d.get("state") == "opened" else "closed",
        author_username=str((d.get("author") or {}).get("username") or ""),
        labels=tuple(str(x) for x in d.get("labels") or []),
        url=str(d.get("web_url") or ""),
        repo_full_name=full_name,
    )


class GitLabIssuesMixin:
    _http: HttpClient

    @staticmethod
    def _issue_project(repo: RepoRef) -> str:
        return f"/projects/{gitlab_project_id(repo.provider_repo_id)}"

    def get_issue(self, repo: RepoRef, number: int) -> Issue:
        d = self._http.get_json(f"{self._issue_project(repo)}/issues/{number}")
        return issue_from_json(d, repo.full_name)

    def create_issue(
        self, repo: RepoRef, title: str, body: str, labels: Sequence[str] = ()
    ) -> Issue:
        payload: dict[str, Any] = {"title": title, "description": body}
        if labels:
            payload["labels"] = ",".join(labels)
        d = self._http.request("POST", f"{self._issue_project(repo)}/issues", json=payload).json()
        return issue_from_json(d, repo.full_name)

    def comment_on_issue(self, repo: RepoRef, number: int, body: str) -> str:
        d = self._http.request(
            "POST", f"{self._issue_project(repo)}/issues/{number}/notes", json={"body": body}
        ).json()
        return str(d["id"])

    def add_labels(
        self, repo: RepoRef, number: int, labels: Sequence[str], *, merge_request: bool = False
    ) -> None:
        """Issue labels; ``merge_request=True`` labels the MR with that iid instead."""
        if not labels:
            return
        kind = "merge_requests" if merge_request else "issues"
        self._http.request(
            "PUT",
            f"{self._issue_project(repo)}/{kind}/{number}",
            json={"add_labels": ",".join(labels)},
        )

    def list_labels(self, repo: RepoRef) -> list[str]:
        out: list[str] = []
        for lb in self._http.paginate(f"{self._issue_project(repo)}/labels", max_pages=2):
            out.append(str(lb["name"]))
            if len(out) >= MAX_LABELS:
                break
        return out

    def recent_committers(
        self, repo: RepoRef, path: str | None = None, limit: int = 10
    ) -> list[str]:
        """GitLab commits carry author names/emails, not usernames: the names are resolved to
        project members by exact name match; unmatched authors are skipped."""
        params: dict[str, Any] = {"per_page": min(100, max(limit * 3, 10))}
        if path:
            params["path"] = path
        commits = self._http.get_json(
            f"{self._issue_project(repo)}/repository/commits", params=params
        )
        names: list[str] = []
        for c in commits or []:
            name = str(c.get("author_name") or "")
            if name and name not in names:
                names.append(name)
        if not names:
            return []
        members = self._http.get_json(
            f"{self._issue_project(repo)}/members/all", params={"per_page": 100}
        )
        by_name = {
            str(m.get("name") or "").lower(): str(m.get("username") or "") for m in members or []
        }
        out: list[str] = []
        for n in names:
            user = by_name.get(n.lower())
            if user and user not in out:
                out.append(user)
            if len(out) >= limit:
                break
        return out
