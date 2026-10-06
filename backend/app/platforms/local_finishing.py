"""In-memory Phase 4 platform writes for ``LocalPlatform`` (tests, evals)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.platforms.base import PullRequest, RepoRef
from app.platforms.finishing import CiJobLog, FileChange, PushRejected


@dataclass(frozen=True)
class PushedCommit:
    repo_id: str
    branch: str
    parents: tuple[str, ...]
    message: str
    changes: tuple[FileChange, ...]
    sha: str
    created_branch: bool


@dataclass
class LocalFinishingState:
    commits: list[PushedCommit] = field(default_factory=list)
    opened: list[PullRequest] = field(default_factory=list)
    # (repo_id, branch) -> tip sha; unknown branches accept any parent
    branch_tips: dict[tuple[str, str], str] = field(default_factory=dict)
    ci_logs: dict[tuple[str, str], list[CiJobLog]] = field(default_factory=dict)
    next_pr_number: int = 1000


class LocalFinishingMixin:
    @property
    def finishing(self) -> LocalFinishingState:
        state = self.__dict__.get("_finishing_state")
        if state is None:
            state = LocalFinishingState()
            self.__dict__["_finishing_state"] = state
        return state

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
        st = self.finishing
        key = (repo.provider_repo_id, branch)
        tip = st.branch_tips.get(key)
        if create_branch and tip is not None:
            raise PushRejected(f"branch {branch} already exists")
        if not create_branch and tip is not None and tip != parent_sha:
            raise PushRejected(f"branch {branch} moved")
        digest = hashlib.sha1(  # noqa: S324 - fake commit id, not security relevant
            f"{branch}:{parent_sha}:{message}:{len(st.commits)}".encode()
        ).hexdigest()
        st.commits.append(
            PushedCommit(
                repo.provider_repo_id,
                branch,
                (parent_sha, *extra_parents),
                message,
                tuple(changes),
                digest,
                create_branch,
            )
        )
        st.branch_tips[key] = digest
        return digest

    def open_pull_request(
        self, repo: RepoRef, head: str, base: str, title: str, body: str
    ) -> PullRequest:
        st = self.finishing
        st.next_pr_number += 1
        pr = PullRequest(
            number=st.next_pr_number,
            title=title,
            body=body,
            author_username="hootpr[bot]",
            state="open",
            is_draft=False,
            base_ref=base,
            head_ref=head,
            base_sha="",
            head_sha=st.branch_tips.get((repo.provider_repo_id, head), ""),
            labels=(),
            url=f"https://local/{repo.full_name}/pull/{st.next_pr_number}",
        )
        st.opened.append(pr)
        return pr

    def get_ci_logs(
        self,
        repo: RepoRef,
        sha: str,
        *,
        run_id: str | None = None,
        max_jobs: int = 5,
        max_log_kb: int = 32,
    ) -> list[CiJobLog]:
        logs = self.finishing.ci_logs.get((repo.provider_repo_id, sha), [])
        if run_id:
            logs = [j for j in logs if j.run_id == run_id]
        return logs[:max_jobs]
