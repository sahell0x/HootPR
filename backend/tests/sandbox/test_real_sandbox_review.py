"""Needs Docker + the hootpr/sandbox image (`make test-sandbox`). Proves isolation (spec §4.3) and
that one review fits the t3.small budget (spec §11.3, §16 row 2): sandbox < 768 MB, worker
< 256 MB peak RSS."""

import os
import resource
from pathlib import Path

import docker
import pytest
from uuid_utils.compat import uuid7

from app.config.schema import HootPRConfig
from app.platforms.base import CloneCredentials, PullRequest, RepoRef
from app.platforms.local import LocalPlatform
from app.review.engine import EngineDeps, EngineInputs, run_engine
from app.review.trace import InMemoryTraceSink
from app.sandbox.base import sandbox_session
from app.sandbox.docker import DockerSandboxManager
from app.settings import Settings
from tests.fakes.engine_llm import EngineFakeLLM, make_test_gateway
from tests.helpers_git import make_git_repo

pytestmark = pytest.mark.sandbox
IMAGE = os.environ.get("SANDBOX_IMAGE", "hootpr/sandbox:latest")
FILES = {
    "app/db.py": "import os\n\n\ndef get(conn, uid):\n    return conn.execute('select 1')\n",
    "app/api.py": "from app.db import get\n\n\ndef show(conn, uid):\n    return get(conn, uid)\n",
    "web/api.ts": "export function f(x: any) {\n  return eval(x)\n}\n",
    "scripts/run.sh": "#!/bin/sh\necho $1\n",
    "Dockerfile": "FROM python:latest\nRUN pip install flask\n",
}


def manager() -> DockerSandboxManager:
    return DockerSandboxManager(docker.from_env(), image=IMAGE, network="hootpr_sandbox_egress")


def test_sandbox_is_hardened_and_sealed(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "src", {"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    with sandbox_session(manager(), "sec-test", mem_mb=768, cpus=1.0) as sb:
        sb.clone(
            CloneCredentials(url=f"file://{repo.path}", username="l", token=""), repo.head_sha, 50
        )
        sb.seal()

        def run(*argv: str) -> str:
            r = sb.exec(list(argv), timeout_s=20, max_output_kb=16, workdir="/")
            return r.stdout.strip() if r.ok else f"FAILED({r.exit_code})"

        assert run("id", "-u") == "10001"
        assert run("touch", "/etc/hootpr").startswith("FAILED")  # read-only root
        assert run("touch", "/work/ok") == "" and run("touch", "/tmp/ok") == ""  # noqa: S108 - in-container tmpfs
        assert run("cat", "/sys/fs/cgroup/memory.max") == str(768 * 1024 * 1024)
        assert run("cat", "/sys/fs/cgroup/pids.max") == "256"
        net = run("python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), 3)")
        assert net.startswith("FAILED")  # sealed: no network
        assert run("git", "-C", "/work/repo", "rev-parse", "HEAD") == repo.head_sha


def test_full_review_fits_the_t3_small_budget(tmp_path: Path, settings: Settings) -> None:
    cfg_settings = settings.model_copy(update={"sandbox_image": IMAGE})
    head: dict[str, str | None] = {k: v + "\n# changed\n" for k, v in FILES.items()}
    head["web/api.ts"] = FILES["web/api.ts"] + "\n// changed\n"
    repo = make_git_repo(tmp_path / "src", FILES, head)
    ref = RepoRef("github", "1", "acme/web")
    lp = LocalPlatform()
    pr = PullRequest(
        1, "t", "", "a", "open", False, "main", "f", repo.base_sha, repo.head_sha, (), ""
    )
    lp.add_pull_request(ref, pr, repo.files)
    lp.register_repo_path(ref, repo.path)
    fake = EngineFakeLLM()
    gw, _ = make_test_gateway(fake)
    sink = InMemoryTraceSink()
    res = run_engine(
        EngineInputs(uuid7(), None, ref, pr, repo.base_sha, repo.head_sha, False, HootPRConfig()),
        EngineDeps(lp, manager(), gw, sink, cfg_settings),
    )
    assert res.status == "reviewed"
    status = {r.tool: r.status for r in res.tool_runs}
    assert status["ruff"] == "ok" and status["shellcheck"] == "ok" and status["hadolint"] == "ok"
    graph = next(s for s in sink.stages if s.name == "graph")
    assert graph.status == "ok" and graph.detail is not None
    assert not graph.detail.startswith("0 symbols")
    assert res.sandbox_peak_mb is not None and res.sandbox_peak_mb < 768
    worker_peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux
    print(f"budget: sandbox peak {res.sandbox_peak_mb} MB, worker peak {worker_peak_mb:.0f} MB")
    assert worker_peak_mb < 256, f"worker peaked at {worker_peak_mb:.0f} MB"


def test_agent_shell_cannot_hang_the_exec_stream(tmp_path: Path) -> None:
    """A `setsid` background process must not keep docker's attach stream (and the review) open."""
    import time

    repo = make_git_repo(tmp_path / "src", {"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    with sandbox_session(manager(), "shell-test", mem_mb=768, cpus=1.0) as sb:
        sb.clone(
            CloneCredentials(url=f"file://{repo.path}", username="l", token=""), repo.head_sha, 50
        )
        sb.seal()
        started = time.monotonic()
        r = sb.shell("setsid sleep 9999 & nohup sleep 9999 >/dev/null 2>&1 & echo hi", timeout_s=5,
                     max_output_kb=16)  # fmt: skip
        assert time.monotonic() - started < 10 and r.stdout.strip() == "hi" and r.exit_code == 0
        left = sb.exec(
            ["sh", "-c", "cat /proc/[0-9]*/cmdline | tr '\\0' ' '; echo"],
            timeout_s=10,
            max_output_kb=4,
        )
        assert "sleep 9999" not in left.stdout, left.stdout  # leftovers were killed
        slow = sb.shell("sleep 30; echo late", timeout_s=2, max_output_kb=16)
        assert slow.timed_out and "late" not in slow.stdout
        big = sb.shell("yes x | head -c 100000", timeout_s=5, max_output_kb=1)
        assert big.truncated and len(big.stdout) == 1024
        assert sb.shell("echo err >&2; exit 3", timeout_s=5, max_output_kb=1).exit_code == 3
