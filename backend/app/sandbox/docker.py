"""Per-job sandbox containers through the docker socket proxy (spec §4.3, plan Q3/Q4).

The worker never mounts the Docker socket and never builds or pulls images: it talks to
``DOCKER_HOST`` (tcp://docker-proxy:2375), which only allows containers, exec and networks.
"""

from __future__ import annotations

import base64
import contextlib
import re
import secrets
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docker
import docker.errors

from app.platforms.base import CloneCredentials
from app.sandbox.base import (
    CloneError,
    ExecResult,
    SandboxUnavailable,
    UnsafePath,
    redact,
    safe_relpath,
)

if TYPE_CHECKING:
    from app.settings import Settings

SANDBOX_LABEL = "org.hootpr.sandbox"
WORK_DIR = "/work"
REPO_DIR = "/work/repo"
TOOLS_DIR = "/opt/hootpr/tools"
USER = "10001:10001"
SANDBOX_UID = 10001
_SHA = re.compile(r"[0-9a-fA-F]{7,64}|[0-9A-Za-z]{40}|[0-9A-Za-z]{64}")  # else: a branch name
CLONE_TIMEOUT_S = 300
STDERR_MAX_KB = 16
_MIB = 1024 * 1024
# Agent shell commands write to files, never to the exec's stdout pipe: a `setsid sleep 9999 &`
# cannot hold the docker attach stream open. When the command ends (or its own timeout fires),
# every other sandbox process except PID 1, this script and its `timeout` parent is killed.
SHELL_WRAPPER = r"""
d=$(mktemp -d) || exit 125
setsid --wait timeout -k 1 "$2" bash -c "$1" >"$d/o" 2>"$d/e" </dev/null &
wait $!
c=$?
for q in /proc/[0-9]*; do
  q=${q#/proc/}
  [ "$q" -eq 1 ] || [ "$q" -eq $$ ] || [ "$q" -eq "$PPID" ] || kill -KILL "$q" 2>/dev/null
done
head -c "$3" "$d/o"
head -c 16384 "$d/e" >&2
rm -rf "$d"
exit $c
"""


class DockerSandbox:
    repo_dir = REPO_DIR
    tools_dir = TOOLS_DIR
    python = "python3"

    def __init__(self, client: docker.DockerClient, container: Any, network: str) -> None:
        self._client = client
        self._container = container
        self._network = network

    # --- clone -----------------------------------------------------------------------------
    def clone(
        self, creds: CloneCredentials, ref: str, depth: int, *, extra_refs: Sequence[str] = ()
    ) -> None:
        if creds.url.startswith("file://"):
            self._upload_local(Path(creds.url.removeprefix("file://")))
        else:
            # The token only ever travels as an extra header on the git command line: never in
            # a URL, a remote, a config file or a log line (spec §4.3).
            auth = base64.b64encode(f"{creds.username}:{creds.token}".encode()).decode()
            header = f"http.extraHeader=Authorization: Basic {auth}"
            self._git(["git", "init", "-q", REPO_DIR], creds, auth)
            fetch = [
                "git", "-C", REPO_DIR, "-c", header, "fetch", "-q", "--no-tags",
                f"--depth={depth}", creds.url,
            ]  # fmt: skip
            self._git([*fetch, ref], creds, auth)
            if not _SHA.fullmatch(ref):  # a branch name (repo-level security jobs, phase 6)
                self._git(
                    ["git", "-C", REPO_DIR, "update-ref", "refs/hootpr/target", "FETCH_HEAD"],
                    creds,
                    "",
                )
                ref = "refs/hootpr/target"
            for extra in extra_refs:  # best effort: the diff base may be gone after a force-push
                self.exec(
                    [*fetch, extra], timeout_s=CLONE_TIMEOUT_S, max_output_kb=4, workdir=WORK_DIR
                )
        self._git(["git", "-C", REPO_DIR, "checkout", "-q", "--detach", ref], creds, "")

    def _git(self, argv: list[str], creds: CloneCredentials, auth: str) -> None:
        r = self.exec(argv, timeout_s=CLONE_TIMEOUT_S, max_output_kb=16, workdir=WORK_DIR)
        if not r.ok:
            msg = redact(redact(r.stderr.strip(), auth), creds.token)[:500]
            raise CloneError(msg or f"git exited with {r.exit_code}")

    def _upload_local(self, src: Path) -> None:
        """LocalPlatform/evals: copy a host checkout (with .git) to /work/repo as the sandbox user.

        The tar is spooled to a temp file, never held in worker memory (spec §11.3)."""

        def owned(ti: tarfile.TarInfo) -> tarfile.TarInfo:
            ti.uid = ti.gid = SANDBOX_UID
            ti.uname = ti.gname = "sandbox"
            return ti

        with tempfile.TemporaryFile() as fh:
            with tarfile.open(fileobj=fh, mode="w") as tar:
                tar.add(str(src), arcname="repo", filter=owned)
            fh.seek(0)
            self._client.api.put_archive(self._container.id, WORK_DIR, fh)

    # --- run -------------------------------------------------------------------------------
    def seal(self) -> None:
        with contextlib.suppress(docker.errors.NotFound):
            self._client.networks.get(self._network).disconnect(self._container, force=True)

    def unseal(self) -> None:
        """Reconnect the egress network. Phase 4 only, for the dependency install step; the
        caller always seals again before running tests (spec §10.1)."""
        try:
            self._client.networks.get(self._network).connect(self._container)
        except docker.errors.APIError as exc:
            if "already exists" not in str(exc):
                raise

    def exec(
        self, argv: list[str], *, timeout_s: int, max_output_kb: int, workdir: str | None = None
    ) -> ExecResult:
        started = time.perf_counter()
        cmd = ["timeout", "-k", "2", str(timeout_s), *argv]
        exec_id = self._client.api.exec_create(
            self._container.id,
            cmd,
            workdir=workdir or REPO_DIR,
            user=USER,
            stdout=True,
            stderr=True,
        )["Id"]
        limit = max(0, max_output_kb) * 1024
        err_limit = STDERR_MAX_KB * 1024
        out, err = bytearray(), bytearray()
        truncated = False
        # Streamed: nothing past the cap is ever buffered in the worker.
        for chunk_out, chunk_err in self._client.api.exec_start(exec_id, stream=True, demux=True):
            if chunk_out:
                room = limit - len(out)
                if room > 0:
                    out += chunk_out[:room]
                if len(chunk_out) > max(room, 0):
                    truncated = True
            if chunk_err and len(err) < err_limit:
                err += chunk_err[: err_limit - len(err)]
        code = self._client.api.exec_inspect(exec_id).get("ExitCode")
        exit_code = -1 if code is None else int(code)
        # ``out`` never exceeds the cap: decode it in place (no extra copies of large outputs).
        return ExecResult(
            exit_code,
            out.decode(errors="replace"),
            err.decode(errors="replace"),
            timed_out=exit_code in (124, 137),
            truncated=truncated,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def shell(self, cmd: str, *, timeout_s: int, max_output_kb: int) -> ExecResult:
        limit = max(0, max_output_kb) * 1024
        r = self.exec(
            ["bash", "-c", SHELL_WRAPPER, "hootpr-shell", cmd, str(timeout_s), str(limit + 1)],
            timeout_s=timeout_s + 5,
            max_output_kb=max_output_kb + 1,
        )
        out = r.stdout.encode()
        truncated = r.truncated or len(out) > limit
        stdout = out[:limit].decode(errors="replace") if truncated else r.stdout
        return ExecResult(
            r.exit_code,
            stdout,
            r.stderr,
            timed_out=r.timed_out,
            truncated=truncated,
            duration_ms=r.duration_ms,
        )

    def read_file(self, path: str, *, max_kb: int = 512) -> str:
        full = f"{REPO_DIR}/{safe_relpath(path)}"
        real = self.exec(["readlink", "-f", "--", full], timeout_s=10, max_output_kb=4)
        if not real.ok:
            return ""
        if not real.stdout.strip().startswith(f"{REPO_DIR}/"):
            raise UnsafePath(path)  # symlink escaping the checkout
        r = self.exec(
            ["head", "-c", str(max_kb * 1024), "--", full], timeout_s=10, max_output_kb=max_kb
        )
        return r.stdout if r.ok else ""

    def peak_memory_mb(self) -> int | None:
        r = self.exec(
            ["cat", "/sys/fs/cgroup/memory.peak"], timeout_s=5, max_output_kb=1, workdir="/"
        )
        try:
            return int(r.stdout.strip()) // _MIB
        except ValueError:
            return None

    def destroy(self) -> None:
        with contextlib.suppress(docker.errors.NotFound):
            self._container.remove(force=True, v=True)


class DockerSandboxManager:
    """Creates sandboxes. ``client`` may be a factory so building the manager is offline."""

    def __init__(
        self,
        client: docker.DockerClient | Callable[[], docker.DockerClient],
        *,
        image: str,
        network: str,
    ) -> None:
        self._client_or_factory = client
        self._client: docker.DockerClient | None = None
        self._image = image
        self._network = network
        self._network_ok = False

    @classmethod
    def from_settings(cls, settings: Settings) -> DockerSandboxManager:
        # The socket timeout must outlive the longest exec (tools run up to 10 minutes).
        timeout = (
            max(
                settings.sandbox_tools_timeout_s,
                settings.sandbox_graph_timeout_s,
                settings.finishing_test_timeout_s,
                CLONE_TIMEOUT_S,
            )
            + 60
        )

        def factory() -> docker.DockerClient:
            return docker.DockerClient(base_url=settings.docker_host, timeout=timeout)

        return cls(factory, image=settings.sandbox_image, network=settings.sandbox_network)

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            c = self._client_or_factory
            self._client = c() if callable(c) else c
        return self._client

    def _ensure_network(self) -> None:
        if self._network_ok:
            return
        if not self.client.networks.list(names=[self._network]):
            self.client.networks.create(
                self._network, driver="bridge", labels={SANDBOX_LABEL: "network"}
            )
        self._network_ok = True

    def create(self, job_id: str, *, mem_mb: int, cpus: float) -> DockerSandbox:
        try:
            self._ensure_network()
            container = self.client.containers.create(
                image=self._image,
                command=["sleep", "infinity"],
                name=f"hootpr-sbx-{job_id[:12]}-{secrets.token_hex(3)}",
                user=USER,
                working_dir=WORK_DIR,
                read_only=True,
                tmpfs={"/tmp": "rw,nosuid,nodev,size=64m"},  # noqa: S108 - in-container tmpfs
                mem_limit=f"{mem_mb}m",
                memswap_limit=f"{mem_mb}m",
                nano_cpus=int(cpus * 1_000_000_000),
                pids_limit=256,
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                network=self._network,
                # safe.directory via env: HOME is a tmpfs and uploaded repos may have other owners
                environment={
                    "HOME": "/tmp",  # noqa: S108 - in-container tmpfs
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "safe.directory",
                    "GIT_CONFIG_VALUE_0": "*",
                },
                labels={
                    SANDBOX_LABEL: "1",
                    f"{SANDBOX_LABEL}.job": job_id,
                    f"{SANDBOX_LABEL}.created": str(int(time.time())),
                },
                detach=True,
            )
        except docker.errors.ImageNotFound as exc:
            raise SandboxUnavailable(
                f"sandbox image {self._image} is missing — run `make sandbox-image`"
            ) from exc
        except docker.errors.DockerException as exc:
            raise SandboxUnavailable(f"docker unavailable: {exc}") from exc
        try:
            container.start()
        except docker.errors.DockerException as exc:
            container.remove(force=True, v=True)
            raise SandboxUnavailable(f"sandbox failed to start: {exc}") from exc
        return DockerSandbox(self.client, container, self._network)

    def gc_orphans(self, max_age_s: int, now: float | None = None) -> int:
        """Remove sandboxes older than ``max_age_s`` (a crashed worker never destroyed them)."""
        now = time.time() if now is None else now
        removed = 0
        for c in self.client.containers.list(all=True, filters={"label": SANDBOX_LABEL}):
            try:
                created = int(c.labels.get(f"{SANDBOX_LABEL}.created", "0") or 0)
            except ValueError:
                created = 0
            if now - created > max_age_s:
                try:
                    c.remove(force=True, v=True)
                    removed += 1
                except docker.errors.NotFound:
                    pass
        return removed
