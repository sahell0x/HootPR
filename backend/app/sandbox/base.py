"""Sandbox abstraction (spec §4.3). Implementations: docker (production), local (tests/evals)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from app.platforms.base import CloneCredentials


class SandboxError(Exception):
    pass


class SandboxUnavailable(SandboxError):
    """Image missing, Docker/proxy unreachable."""


class CloneError(SandboxError):
    pass


class RepoTooLarge(SandboxError):
    pass


class UnsafePath(SandboxError):
    pass


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Sandbox(Protocol):
    repo_dir: str
    tools_dir: str
    python: str

    def clone(
        self, creds: CloneCredentials, ref: str, depth: int, *, extra_refs: Sequence[str] = ()
    ) -> None:
        """Check out ``ref`` (detached) in ``repo_dir``; ``extra_refs`` are fetched best effort."""
        ...

    def seal(self) -> None:
        """Cut network access; called after cloning and before any analysis."""
        ...

    def exec(
        self, argv: list[str], *, timeout_s: int, max_output_kb: int, workdir: str | None = None
    ) -> ExecResult:
        """Run ``argv`` (no shell) in ``workdir`` (default ``repo_dir``); stdout is capped."""
        ...

    def shell(self, cmd: str, *, timeout_s: int, max_output_kb: int) -> ExecResult:
        """Run an untrusted ``bash -c`` command (the agent's ``shell`` tool) in ``repo_dir``.

        Background or ``setsid`` processes it leaves behind must never keep the call hanging."""
        ...

    def read_file(self, path: str, *, max_kb: int = 512) -> str:
        """A repo-relative file, capped; ``""`` when missing. ``UnsafePath`` outside the repo."""
        ...

    def peak_memory_mb(self) -> int | None: ...
    def destroy(self) -> None: ...


class SandboxManager(Protocol):
    def create(self, job_id: str, *, mem_mb: int, cpus: float) -> Sandbox: ...


def safe_relpath(path: str) -> str:
    """A repo-relative POSIX path, or ``UnsafePath`` (absolute, ``..``, NUL, empty)."""
    if not path or "\x00" in path:
        raise UnsafePath(repr(path))
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        raise UnsafePath(path)
    rel = str(p)
    if rel in ("", "."):
        raise UnsafePath(path)
    return rel


def cap_bytes(data: bytes, max_kb: int) -> tuple[str, bool]:
    """Decode at most ``max_kb`` KiB (a split multi-byte char is replaced) + truncated flag."""
    limit = max(0, max_kb) * 1024
    truncated = len(data) > limit
    return data[:limit].decode(errors="replace"), truncated


def redact(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


@contextmanager
def sandbox_session(
    manager: SandboxManager, job_id: str, *, mem_mb: int, cpus: float
) -> Iterator[Sandbox]:
    """Create a sandbox and always destroy it, whatever happens inside the block."""
    sb = manager.create(job_id, mem_mb=mem_mb, cpus=cpus)
    try:
        yield sb
    finally:
        sb.destroy()


def repo_size_mb(sb: Sandbox) -> int:
    r = sb.exec(["du", "-sm", sb.repo_dir], timeout_s=60, max_output_kb=4, workdir="/")
    try:
        return int(r.stdout.split()[0])
    except (IndexError, ValueError):
        return 0
