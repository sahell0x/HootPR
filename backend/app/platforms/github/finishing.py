"""GitHub side of Phase 4: Git Data API commits, stacked PRs, Actions logs (spec §10.1).

A mixin of ``GitHubPlatform`` so the platform module stays small. Pushes never run ``git``: the
change set is uploaded as blobs, then a tree, a commit (merge commits allowed) and a
fast-forward-only ref update, all with the installation token.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

import httpx

from app.platforms.base import PlatformError, PrState, PullRequest, RepoRef
from app.platforms.finishing import CiJobLog, FileChange, PushRejected, tail_text
from app.platforms.http import HttpClient

_FAILED = frozenset({"failure", "timed_out", "startup_failure"})
_LOG_TIMEOUT_S = 30.0


def pr_from_json(d: dict[str, Any]) -> PullRequest:
    state: PrState = (
        "merged" if d.get("merged_at") else "open" if d.get("state") == "open" else "closed"
    )
    return PullRequest(
        number=int(d["number"]),
        title=str(d.get("title") or ""),
        body=str(d.get("body") or ""),
        author_username=str((d.get("user") or {}).get("login") or ""),
        state=state,
        is_draft=bool(d.get("draft")),
        base_ref=str(d["base"]["ref"]),
        head_ref=str(d["head"]["ref"]),
        base_sha=str(d["base"].get("sha") or ""),
        head_sha=str(d["head"].get("sha") or ""),
        labels=tuple(str(lb["name"]) for lb in d.get("labels", [])),
        url=str(d.get("html_url") or ""),
    )


def download_tail(url: str, max_kb: int) -> str:
    """Stream a (pre-signed, unauthenticated) log URL keeping only the last ``max_kb`` KiB."""
    limit = max(1, max_kb) * 1024
    buf = bytearray()
    cut = False
    with httpx.stream("GET", url, timeout=_LOG_TIMEOUT_S, follow_redirects=True) as resp:
        if resp.status_code >= 400:
            raise PlatformError(resp.status_code, f"log download: HTTP {resp.status_code}")
        for chunk in resp.iter_bytes():
            buf += chunk
            if len(buf) > 2 * limit:
                del buf[: len(buf) - limit]
                cut = True
    if len(buf) > limit:
        del buf[: len(buf) - limit]
        cut = True
    text = buf.decode(errors="ignore")
    return f"…[log truncated]\n{text}" if cut else text


class GitHubFinishingMixin:
    _http: HttpClient

    @staticmethod
    def _repo_path(repo: RepoRef) -> str:
        return f"/repos/{repo.full_name}"

    # --- commits ---------------------------------------------------------------------------
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
        r = self._repo_path(repo)
        base_commit = self._http.get_json(f"{r}/git/commits/{tree_base or parent_sha}")
        base_tree = str(base_commit["tree"]["sha"])
        items: list[dict[str, Any]] = []
        for ch in changes:
            mode = "100755" if ch.executable else "100644"
            if ch.content is None:
                items.append({"path": ch.path, "mode": mode, "type": "blob", "sha": None})
                continue
            blob = self._http.request(
                "POST",
                f"{r}/git/blobs",
                json={"content": base64.b64encode(ch.content).decode(), "encoding": "base64"},
            ).json()
            items.append({"path": ch.path, "mode": mode, "type": "blob", "sha": blob["sha"]})
        tree_sha = base_tree
        if items:
            tree = self._http.request(
                "POST", f"{r}/git/trees", json={"base_tree": base_tree, "tree": items}
            ).json()
            tree_sha = str(tree["sha"])
        commit = self._http.request(
            "POST",
            f"{r}/git/commits",
            json={"message": message, "tree": tree_sha, "parents": [parent_sha, *extra_parents]},
        ).json()
        sha = str(commit["sha"])
        try:
            if create_branch:
                self._http.request(
                    "POST", f"{r}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha}
                )
            else:
                self._http.request(
                    "PATCH", f"{r}/git/refs/heads/{branch}", json={"sha": sha, "force": False}
                )
        except PlatformError as exc:
            if exc.status_code in (403, 404, 409, 422):
                raise PushRejected(exc.message) from exc
            raise
        return sha

    def open_pull_request(
        self, repo: RepoRef, head: str, base: str, title: str, body: str
    ) -> PullRequest:
        d = self._http.request(
            "POST",
            f"{self._repo_path(repo)}/pulls",
            json={"title": title[:250], "head": head, "base": base, "body": body},
        ).json()
        return pr_from_json(d)

    # --- CI --------------------------------------------------------------------------------
    def get_ci_logs(
        self,
        repo: RepoRef,
        sha: str,
        *,
        run_id: str | None = None,
        max_jobs: int = 5,
        max_log_kb: int = 32,
    ) -> list[CiJobLog]:
        r = self._repo_path(repo)
        if run_id:
            runs = [self._http.get_json(f"{r}/actions/runs/{run_id}")]
        else:
            data = self._http.get_json(
                f"{r}/actions/runs", params={"head_sha": sha, "per_page": 20}
            )
            runs = [x for x in data.get("workflow_runs") or [] if x.get("conclusion") in _FAILED]
        out: list[CiJobLog] = []
        for run in runs:
            jobs = self._http.get_json(
                f"{r}/actions/runs/{run['id']}/jobs", params={"filter": "latest", "per_page": 100}
            )
            for job in jobs.get("jobs") or []:
                if job.get("conclusion") not in _FAILED:
                    continue
                if len(out) >= max_jobs:
                    return out
                step = next(
                    (
                        str(s.get("name"))
                        for s in job.get("steps") or []
                        if s.get("conclusion") in _FAILED
                    ),
                    None,
                )
                out.append(
                    CiJobLog(
                        job_id=str(job["id"]),
                        name=str(job.get("name") or ""),
                        status=str(job.get("conclusion") or "failure"),
                        url=str(job.get("html_url") or ""),
                        log_tail=self._job_log(r, str(job["id"]), max_log_kb),
                        run_id=str(run["id"]),
                        run_name=str(run.get("name") or ""),
                        failed_step=step,
                    )
                )
        return out

    def _job_log(self, r: str, job_id: str, max_kb: int) -> str:
        """``/logs`` answers 302 to a short-lived download URL (fetched without our token)."""
        try:
            resp = self._http.request("GET", f"{r}/actions/jobs/{job_id}/logs")
            location = resp.headers.get("location")
            if resp.status_code in (301, 302, 303, 307, 308) and location:
                return download_tail(location, max_kb)
            return tail_text(resp.text, max_kb)
        except (PlatformError, httpx.HTTPError) as exc:
            return f"[log unavailable: {type(exc).__name__}]"
