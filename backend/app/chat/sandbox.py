"""A sandbox created only when the chat agent first needs it (phase-3 R10, t3.small budget).

A chat that never calls ``shell``/``read_file`` starts no container. Once created, the sandbox
is cloned at the PR head and sealed (no network) before any command runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.platforms.base import CloneCredentials
from app.sandbox.base import ExecResult, Sandbox, SandboxManager
from app.settings import Settings


class LazySandbox:
    def __init__(
        self,
        manager: SandboxManager,
        job_id: str,
        creds: Callable[[], CloneCredentials],
        head_sha: str,
        settings: Settings,
    ) -> None:
        self._mgr, self._job, self._creds = manager, job_id, creds
        self._head, self._s = head_sha, settings
        self._sb: Sandbox | None = None
        self._failed: Exception | None = None

    @property
    def created(self) -> bool:
        return self._sb is not None

    def _get(self) -> Sandbox:
        if self._failed is not None:
            raise self._failed  # a failed clone is not retried on every tool call
        if self._sb is None:
            sb = self._mgr.create(
                self._job, mem_mb=self._s.sandbox_mem_mb, cpus=self._s.sandbox_cpus
            )
            # Set before cloning: a failed clone still leaves a container for destroy().
            self._sb = sb
            try:
                sb.clone(self._creds(), self._head, self._s.sandbox_clone_depth)
                sb.seal()
            except Exception as exc:
                self._failed = exc
                raise
        return self._sb

    @property
    def repo_dir(self) -> str:
        return self._get().repo_dir

    @repo_dir.setter
    def repo_dir(self, value: str) -> None:
        raise AttributeError("repo_dir is fixed by the underlying sandbox")

    @property
    def tools_dir(self) -> str:
        return self._get().tools_dir

    @tools_dir.setter
    def tools_dir(self, value: str) -> None:
        raise AttributeError("tools_dir is fixed by the underlying sandbox")

    @property
    def python(self) -> str:
        return self._get().python

    @python.setter
    def python(self, value: str) -> None:
        raise AttributeError("python is fixed by the underlying sandbox")

    def clone(
        self, creds: CloneCredentials, ref: str, depth: int, *, extra_refs: Sequence[str] = ()
    ) -> None:
        raise RuntimeError("LazySandbox clones itself on first use")

    def seal(self) -> None:
        self._get()

    def exec(
        self, argv: list[str], *, timeout_s: int, max_output_kb: int, workdir: str | None = None
    ) -> ExecResult:
        return self._get().exec(
            argv, timeout_s=timeout_s, max_output_kb=max_output_kb, workdir=workdir
        )

    def shell(self, cmd: str, *, timeout_s: int, max_output_kb: int) -> ExecResult:
        return self._get().shell(cmd, timeout_s=timeout_s, max_output_kb=max_output_kb)

    def read_file(self, path: str, *, max_kb: int = 512) -> str:
        return self._get().read_file(path, max_kb=max_kb)

    def peak_memory_mb(self) -> int | None:
        return self._sb.peak_memory_mb() if self._sb is not None else None

    def destroy(self) -> None:
        if self._sb is not None:
            self._sb.destroy()
