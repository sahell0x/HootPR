"""Host-directory sandbox for tests, evals and local dev (plan Q2).

This is NOT isolation: it is refused in production by ``Settings``. Commands get a minimal
environment so host secrets (LLM keys, DB URLs) never leak into repository commands.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from app.platforms.base import CloneCredentials
from app.sandbox.base import CloneError, ExecResult, UnsafePath, cap_bytes, redact, safe_relpath

DEFAULT_TOOLS_DIR = Path(__file__).resolve().parents[3] / "sandbox" / "hootpr_tools"
_BASE_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
}
_STDERR_KB = 16


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class LocalSandbox:
    def __init__(
        self, root: Path, tools_dir: Path, remote_map: Callable[[str], str | None] | None
    ) -> None:
        self.root = root
        self.repo_dir = str(root / "repo")
        self.tools_dir = str(tools_dir)
        self.python = sys.executable
        self._remote_map = remote_map
        self.sealed = False

    def _env(self) -> dict[str, str]:
        path = f"{Path(sys.executable).parent}:{_BASE_ENV['PATH']}"
        return {
            **_BASE_ENV,
            "PATH": path,
            "HOME": str(self.root),
            "GIT_CONFIG_GLOBAL": str(self.root / ".gitconfig"),
            # run_tools.py caches (go, trivy, phpstan) stay inside this temp dir
            "HOOTPR_WORK_CACHE": str(self.root / "cache"),
        }

    def clone(
        self, creds: CloneCredentials, ref: str, depth: int, *, extra_refs: Sequence[str] = ()
    ) -> None:
        # A local clone copies every reachable object, so ``depth``/``extra_refs`` need no fetch.
        src: str | None = None
        if creds.url.startswith("file://"):
            src = creds.url.removeprefix("file://")
        elif self._remote_map is not None:
            src = self._remote_map(creds.url)
        if src is None:
            raise CloneError(f"local sandbox cannot clone {creds.url.split('@')[-1]}")
        for argv in (
            ["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", src, self.repo_dir],
            ["git", "-C", self.repo_dir, "checkout", "--quiet", "--detach", ref],
        ):
            r = self.exec(argv, timeout_s=120, max_output_kb=16, workdir=str(self.root))
            if not r.ok:
                msg = redact(r.stderr.strip(), creds.token)[:500]
                raise CloneError(msg or f"git exited with {r.exit_code}")

    def seal(self) -> None:
        self.sealed = True

    def unseal(self) -> None:
        self.sealed = False

    def exec(
        self, argv: list[str], *, timeout_s: int, max_output_kb: int, workdir: str | None = None
    ) -> ExecResult:
        started = time.perf_counter()
        cwd = workdir or self.repo_dir
        try:
            p = subprocess.run(  # noqa: S603 - argv list, no shell
                argv, cwd=cwd, capture_output=True, timeout=timeout_s, env=self._env(), check=False
            )
        except subprocess.TimeoutExpired as exc:
            out, trunc = cap_bytes(exc.stdout or b"", max_output_kb)
            err, _ = cap_bytes(exc.stderr or b"", _STDERR_KB)
            return ExecResult(
                124, out, err, timed_out=True, truncated=trunc, duration_ms=_ms(started)
            )
        except OSError as exc:  # binary or workdir missing
            return ExecResult(127, "", str(exc), duration_ms=_ms(started))
        out, trunc = cap_bytes(p.stdout, max_output_kb)
        err, _ = cap_bytes(p.stderr, _STDERR_KB)
        return ExecResult(p.returncode, out, err, truncated=trunc, duration_ms=_ms(started))

    def shell(self, cmd: str, *, timeout_s: int, max_output_kb: int) -> ExecResult:
        return self.exec(["bash", "-c", cmd], timeout_s=timeout_s, max_output_kb=max_output_kb)

    def read_file(self, path: str, *, max_kb: int = 512) -> str:
        rel = safe_relpath(path)
        base = Path(self.repo_dir).resolve()
        target = (base / rel).resolve()
        if base not in target.parents:
            raise UnsafePath(path)  # symlink escaping the checkout
        try:
            with target.open("rb") as fh:
                return cap_bytes(fh.read(max_kb * 1024 + 1), max_kb)[0]
        except OSError:
            return ""

    def peak_memory_mb(self) -> int | None:
        return None

    def destroy(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class LocalSandboxManager:
    def __init__(
        self,
        tools_dir: Path | None = None,
        *,
        base_dir: Path | None = None,
        remote_map: Callable[[str], str | None] | None = None,
    ) -> None:
        self.tools_dir = tools_dir or DEFAULT_TOOLS_DIR
        self.base_dir = base_dir
        self.remote_map = remote_map

    def create(self, job_id: str, *, mem_mb: int, cpus: float) -> LocalSandbox:
        root = Path(tempfile.mkdtemp(prefix=f"hootpr-{job_id[:8]}-", dir=self.base_dir))
        return LocalSandbox(root, self.tools_dir, self.remote_map)
