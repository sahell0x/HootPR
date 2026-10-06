"""GitLab side of Phase 4: Commits API pushes, stacked MRs, pipeline job logs (spec §10.1).

A mixin of ``GitLabPlatform``. Plain commits use the Commits API with the bot token (the branch
tip is checked first: GitLab has no fast-forward-only switch). The Commits API cannot create
merge commits, so merge-conflict resolutions go through ``gitpush.push_merge_commit`` (worker-side
``git``, still outside the sandbox).
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

from app.platforms.base import PlatformError, PrState, PullRequest, RepoRef
from app.platforms.finishing import CiJobLog, FileChange, PushRejected, tail_text
from app.platforms.gitlab.gitpush import push_merge_commit
from app.platforms.http import HttpClient

_PR_STATE: dict[str, PrState] = {"opened": "open", "merged": "merged"}


def mr_from_json(d: dict[str, Any]) -> PullRequest:
    refs = d.get("diff_refs") or {}
    return PullRequest(
        number=int(d["iid"]),
        title=str(d.get("title") or ""),
        body=str(d.get("description") or ""),
        author_username=str((d.get("author") or {}).get("username") or ""),
        state=_PR_STATE.get(str(d.get("state")), "closed"),
        is_draft=bool(d.get("draft") or d.get("work_in_progress")),
        base_ref=str(d.get("target_branch") or ""),
        head_ref=str(d.get("source_branch") or ""),
        base_sha=str(refs.get("base_sha") or ""),
        head_sha=str(refs.get("head_sha") or d.get("sha") or ""),
        labels=tuple(str(x) for x in d.get("labels", [])),
        url=str(d.get("web_url") or ""),
    )


def commit_actions(changes: Sequence[FileChange]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ch in changes:
        if ch.content is None:
            out.append({"action": "delete", "file_path": ch.path})
            continue
        item: dict[str, Any] = {
            "action": "create" if ch.is_new else "update",
            "file_path": ch.path,
            "content": base64.b64encode(ch.content).decode(),
            "encoding": "base64",
        }
        if ch.executable:
            item["execute_filemode"] = True
        out.append(item)
    return out


class GitLabFinishingMixin:
    _http: HttpClient
    _token: str
    _web: str

    @staticmethod
    def _project(repo: RepoRef) -> str:
        return f"/projects/{repo.provider_repo_id}"

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
        p = self._project(repo)
        if extra_parents:
            if not create_branch:
                self._check_tip(p, branch, parent_sha)
            return push_merge_commit(
                url=f"{self._web}/{repo.full_name}.git",
                username="oauth2",
                token=self._token,
                branch=branch,
                parents=[parent_sha, *extra_parents],
                tree_base=tree_base or parent_sha,
                message=message,
                changes=changes,
            )
        if tree_base and tree_base != parent_sha:
            raise ValueError("GitLab commits are always relative to their parent")
        if not changes:
            raise ValueError("nothing to commit")
        payload: dict[str, Any] = {
            "branch": branch,
            "commit_message": message,
            "actions": commit_actions(changes),
        }
        if create_branch:
            payload["start_sha"] = parent_sha
        else:
            self._check_tip(p, branch, parent_sha)
        try:
            d = self._http.request("POST", f"{p}/repository/commits", json=payload).json()
        except PlatformError as exc:
            if exc.status_code in (400, 403, 409):
                raise PushRejected(exc.message) from exc
            raise
        return str(d["id"])

    def _check_tip(self, p: str, branch: str, parent_sha: str) -> None:
        tip = self._http.get_json(f"{p}/repository/branches/{quote(branch, safe='')}")
        current = str((tip.get("commit") or {}).get("id") or "")
        if current != parent_sha:
            raise PushRejected(f"branch {branch} moved to {current[:12]}")

    def open_pull_request(
        self, repo: RepoRef, head: str, base: str, title: str, body: str
    ) -> PullRequest:
        d = self._http.request(
            "POST",
            f"{self._project(repo)}/merge_requests",
            json={
                "source_branch": head,
                "target_branch": base,
                "title": title[:250],
                "description": body,
                "remove_source_branch": True,
            },
        ).json()
        return mr_from_json(d)

    def get_ci_logs(
        self,
        repo: RepoRef,
        sha: str,
        *,
        run_id: str | None = None,
        max_jobs: int = 5,
        max_log_kb: int = 32,
    ) -> list[CiJobLog]:
        p = self._project(repo)
        if run_id:
            pipelines: list[dict[str, Any]] = [{"id": run_id, "ref": ""}]
        else:
            pipelines = list(
                self._http.get_json(
                    f"{p}/pipelines", params={"sha": sha, "status": "failed", "per_page": 5}
                )
                or []
            )
        out: list[CiJobLog] = []
        for pl in pipelines:
            jobs = self._http.get_json(
                f"{p}/pipelines/{pl['id']}/jobs", params={"scope[]": "failed", "per_page": 100}
            )
            for job in jobs or []:
                if len(out) >= max_jobs:
                    return out
                if job.get("allow_failure"):
                    continue
                try:
                    trace = self._http.request("GET", f"{p}/jobs/{job['id']}/trace").text
                    log = tail_text(trace, max_log_kb)
                except PlatformError as exc:
                    log = f"[log unavailable: HTTP {exc.status_code}]"
                out.append(
                    CiJobLog(
                        job_id=str(job["id"]),
                        name=str(job.get("name") or ""),
                        status=str(job.get("status") or "failed"),
                        url=str(job.get("web_url") or ""),
                        log_tail=log,
                        run_id=str(pl["id"]),
                        run_name=str(job.get("stage") or pl.get("ref") or ""),
                        failed_step=str(job.get("stage")) if job.get("stage") else None,
                    )
                )
        return out
