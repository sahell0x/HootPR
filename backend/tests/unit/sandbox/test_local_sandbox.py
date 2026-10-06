import sys
from pathlib import Path

import pytest

from app.platforms.base import CloneCredentials
from app.sandbox.base import (
    CloneError,
    ExecResult,
    SandboxError,
    UnsafePath,
    cap_bytes,
    repo_size_mb,
    safe_relpath,
    sandbox_session,
)
from app.sandbox.local import DEFAULT_TOOLS_DIR, LocalSandboxManager
from tests.helpers_git import GitRepo, make_git_repo, write_stub_tools


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    return make_git_repo(
        tmp_path / "src", {"a.py": "x = 1\n"}, {"a.py": "x = 2\n", "b.py": "y = 3\n"}
    )


def creds(path: Path) -> CloneCredentials:
    return CloneCredentials(url=f"file://{path}", username="local", token="")


def test_clone_checks_out_head_and_exec_runs_in_repo(tmp_path: Path, repo: GitRepo) -> None:
    mgr = LocalSandboxManager(base_dir=tmp_path)
    with sandbox_session(mgr, "job1", mem_mb=768, cpus=1.0) as sb:
        sb.clone(creds(repo.path), repo.head_sha, 50, extra_refs=[repo.base_sha])
        sb.seal()
        r = sb.exec(["git", "rev-parse", "HEAD"], timeout_s=10, max_output_kb=4)
        assert r.ok and r.stdout.strip() == repo.head_sha
        base = sb.exec(["git", "cat-file", "-t", repo.base_sha], timeout_s=10, max_output_kb=4)
        assert base.stdout.strip() == "commit"
        assert sb.read_file("b.py") == "y = 3\n"
        root = Path(sb.repo_dir).parent
    assert not root.exists()  # destroyed on exit


def test_session_destroys_sandbox_on_error(tmp_path: Path) -> None:
    mgr = LocalSandboxManager(base_dir=tmp_path)
    with pytest.raises(RuntimeError), sandbox_session(mgr, "j", mem_mb=768, cpus=1.0) as sb:
        root = Path(sb.repo_dir).parent
        raise RuntimeError("boom")
    assert not root.exists()


def test_exec_timeout_and_output_cap(tmp_path: Path, repo: GitRepo) -> None:
    with sandbox_session(LocalSandboxManager(base_dir=tmp_path), "j", mem_mb=768, cpus=1.0) as sb:
        sb.clone(creds(repo.path), repo.head_sha, 50)
        slow = sb.exec(["sleep", "5"], timeout_s=1, max_output_kb=4)
        assert slow.timed_out and not slow.ok
        big = sb.exec([sb.python, "-c", "print('x' * 10000)"], timeout_s=10, max_output_kb=1)
        assert big.truncated and len(big.stdout) == 1024
        missing = sb.exec(["definitely-not-a-binary-xyz"], timeout_s=5, max_output_kb=1)
        assert missing.exit_code == 127 and not missing.ok


def test_read_file_rejects_path_traversal(tmp_path: Path, repo: GitRepo) -> None:
    with sandbox_session(LocalSandboxManager(base_dir=tmp_path), "j", mem_mb=768, cpus=1.0) as sb:
        sb.clone(creds(repo.path), repo.head_sha, 50)
        for bad in ("../../etc/passwd", "/etc/passwd", "", "a\x00b", "."):
            with pytest.raises(UnsafePath):
                sb.read_file(bad)
        (Path(sb.repo_dir) / "link").symlink_to("/etc/passwd")
        with pytest.raises(UnsafePath):
            sb.read_file("link")
        assert sb.read_file("does/not/exist.py") == ""


def test_read_file_caps_size(tmp_path: Path, repo: GitRepo) -> None:
    with sandbox_session(LocalSandboxManager(base_dir=tmp_path), "j", mem_mb=768, cpus=1.0) as sb:
        sb.clone(creds(repo.path), repo.head_sha, 50)
        (Path(sb.repo_dir) / "big.txt").write_text("z" * 5000)
        assert len(sb.read_file("big.txt", max_kb=1)) == 1024


def test_exec_does_not_leak_host_environment(
    tmp_path: Path, repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_REVIEW_API_KEY", "sk-secret")
    with sandbox_session(LocalSandboxManager(base_dir=tmp_path), "j", mem_mb=768, cpus=1.0) as sb:
        sb.clone(creds(repo.path), repo.head_sha, 50)
        assert "sk-secret" not in sb.exec(["env"], timeout_s=5, max_output_kb=64).stdout


def test_clone_of_non_file_url_uses_remote_map_or_fails(tmp_path: Path, repo: GitRepo) -> None:
    https = CloneCredentials(url="https://github.com/acme/web.git", username="x", token="t0k")
    with sandbox_session(LocalSandboxManager(base_dir=tmp_path), "j", mem_mb=768, cpus=1.0) as sb:
        with pytest.raises(CloneError) as exc:
            sb.clone(https, repo.head_sha, 50)
        assert "t0k" not in str(exc.value)
    mapped = LocalSandboxManager(base_dir=tmp_path, remote_map=lambda url: str(repo.path))
    with sandbox_session(mapped, "j2", mem_mb=768, cpus=1.0) as sb:
        sb.clone(https, repo.head_sha, 50)
        assert sb.read_file("b.py") == "y = 3\n"


def test_clone_of_unknown_ref_is_clone_error(tmp_path: Path, repo: GitRepo) -> None:
    mgr = LocalSandboxManager(base_dir=tmp_path)
    with sandbox_session(mgr, "j", mem_mb=768, cpus=1.0) as sb, pytest.raises(CloneError):
        sb.clone(creds(repo.path), "f" * 40, 50)
    assert issubclass(CloneError, SandboxError)


def test_tools_dir_and_python_run_stub_scripts(tmp_path: Path, repo: GitRepo) -> None:
    tools = write_stub_tools(tmp_path / "tools", tools={"version": 1, "runs": [], "findings": []})
    mgr = LocalSandboxManager(tools, base_dir=tmp_path)
    with sandbox_session(mgr, "j", mem_mb=768, cpus=1.0) as sb:
        sb.clone(creds(repo.path), repo.head_sha, 50)
        assert sb.python == sys.executable
        r = sb.exec([sb.python, f"{sb.tools_dir}/run_tools.py"], timeout_s=10, max_output_kb=64)
        assert r.ok and '"findings": []' in r.stdout
        assert repo_size_mb(sb) >= 0
        assert sb.peak_memory_mb() is None
    assert LocalSandboxManager().tools_dir == DEFAULT_TOOLS_DIR
    assert DEFAULT_TOOLS_DIR.parts[-2:] == ("sandbox", "hootpr_tools")


def test_safe_relpath_and_cap_bytes() -> None:
    assert safe_relpath("src/a.py") == "src/a.py"
    assert safe_relpath("./src/a.py") == "src/a.py"
    assert cap_bytes(b"abcdef", 0) == ("", True)
    assert cap_bytes(b"abc", 1) == ("abc", False)
    assert cap_bytes("é".encode() * 600, 1)[1] is True
    assert ExecResult(0, "", "").ok and not ExecResult(0, "", "", timed_out=True).ok
