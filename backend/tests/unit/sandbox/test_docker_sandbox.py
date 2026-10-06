import base64
import io
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import docker.errors
import pytest

from app.platforms.base import CloneCredentials
from app.sandbox.base import CloneError, SandboxUnavailable, UnsafePath
from app.sandbox.docker import SANDBOX_LABEL, DockerSandbox, DockerSandboxManager
from app.settings import Settings

Chunks = list[tuple[bytes | None, bytes | None]]


@dataclass
class FakeContainer:
    id: str = "c1"
    labels: dict[str, str] = field(default_factory=dict)
    removed: list[dict[str, Any]] = field(default_factory=list)
    started: bool = False

    def start(self) -> None:
        self.started = True

    def remove(self, **kw: Any) -> None:
        self.removed.append(kw)


class FakeAPI:
    def __init__(self) -> None:
        self.execs: list[dict[str, Any]] = []
        self.results: list[tuple[Chunks, int | None]] = []
        self.archive: tuple[str, bytes] | None = None
        self._code: int | None = 0

    def exec_create(self, container: str, cmd: list[str], **kw: Any) -> dict[str, str]:
        self.execs.append({"container": container, "cmd": cmd, **kw})
        return {"Id": f"e{len(self.execs)}"}

    def exec_start(self, exec_id: str, stream: bool, demux: bool) -> Iterator[Any]:
        assert stream and demux
        chunks, code = self.results.pop(0) if self.results else ([(b"", None)], 0)
        self._code = code
        return iter(chunks)

    def exec_inspect(self, exec_id: str) -> dict[str, Any]:
        return {"ExitCode": self._code}

    def put_archive(self, container: str, path: str, data: BinaryIO) -> bool:
        self.archive = (path, data.read())
        return True


class FakeNetwork:
    def __init__(self) -> None:
        self.disconnected: list[str] = []

    def disconnect(self, container: Any, force: bool = False) -> None:
        self.disconnected.append(container.id)


class FakeClient:
    def __init__(self, image_missing: bool = False, down: bool = False) -> None:
        self.api = FakeAPI()
        self.net = FakeNetwork()
        self.created: dict[str, Any] = {}
        self.image_missing = image_missing
        self.down = down
        self.listed: list[FakeContainer] = []
        self.networks_created: list[tuple[str, dict[str, Any]]] = []
        self.existing_networks: list[FakeNetwork] = [self.net]
        self.list_kw: dict[str, Any] = {}
        self.container: FakeContainer | None = None
        client = self

        class Containers:
            def create(self, **kw: Any) -> FakeContainer:
                if client.image_missing:
                    raise docker.errors.ImageNotFound("no such image")
                client.created = kw
                client.container = FakeContainer(labels=kw["labels"])
                return client.container

            def list(self, **kw: Any) -> list[FakeContainer]:
                client.list_kw = kw
                return client.listed

        class Networks:
            def get(self, name: str) -> FakeNetwork:
                return client.net

            def list(self, names: list[str]) -> list[FakeNetwork]:
                if client.down:
                    raise docker.errors.DockerException("connection refused")
                return client.existing_networks

            def create(self, name: str, **kw: Any) -> FakeNetwork:
                client.networks_created.append((name, kw))
                return client.net

        self.containers = Containers()
        self.networks = Networks()


def manager(client: FakeClient) -> DockerSandboxManager:
    return DockerSandboxManager(
        client,  # type: ignore[arg-type]
        image="hootpr/sandbox:latest",
        network="hootpr_sandbox_egress",
    )


def test_create_applies_spec_limits() -> None:
    c = FakeClient()
    sb = manager(c).create("0123456789abcdef", mem_mb=768, cpus=1.0)
    kw = c.created
    assert kw["image"] == "hootpr/sandbox:latest"
    assert kw["mem_limit"] == "768m" and kw["memswap_limit"] == "768m"
    assert kw["nano_cpus"] == 1_000_000_000 and kw["pids_limit"] == 256
    assert kw["read_only"] is True and kw["user"] == "10001:10001"
    assert kw["tmpfs"] == {"/tmp": "rw,nosuid,nodev,size=64m"}  # noqa: S108
    assert kw["security_opt"] == ["no-new-privileges:true"] and kw["cap_drop"] == ["ALL"]
    assert kw["network"] == "hootpr_sandbox_egress"
    assert kw["labels"][SANDBOX_LABEL] == "1"
    assert kw["labels"][f"{SANDBOX_LABEL}.job"] == "0123456789abcdef"
    assert "volumes" not in kw and "privileged" not in kw  # /work is the image's anonymous VOLUME
    assert c.container is not None and c.container.started
    assert sb.repo_dir == "/work/repo" and sb.tools_dir == "/opt/hootpr/tools"


def test_egress_network_is_created_once_when_missing() -> None:
    c = FakeClient()
    c.existing_networks = []
    m = manager(c)
    m.create("a", mem_mb=768, cpus=1.0)
    m.create("b", mem_mb=768, cpus=1.0)
    assert [n for n, _ in c.networks_created] == ["hootpr_sandbox_egress"]


def test_missing_image_is_sandbox_unavailable() -> None:
    with pytest.raises(SandboxUnavailable, match="make sandbox-image"):
        manager(FakeClient(image_missing=True)).create("j", mem_mb=768, cpus=1.0)


def test_unreachable_docker_is_sandbox_unavailable() -> None:
    with pytest.raises(SandboxUnavailable, match="docker unavailable"):
        manager(FakeClient(down=True)).create("j", mem_mb=768, cpus=1.0)


def test_exec_streams_with_cap_timeout_wrapper_and_exit_code() -> None:
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    c.api.results.append(([(b"a" * 700, None), (b"b" * 700, b"warn")], 0))
    r = sb.exec(["cat", "x"], timeout_s=20, max_output_kb=1)
    assert r.truncated and len(r.stdout) == 1024 and r.stderr == "warn" and r.ok
    last = c.api.execs[-1]
    assert last["cmd"][:4] == ["timeout", "-k", "2", "20"] and last["cmd"][4:] == ["cat", "x"]
    assert last["user"] == "10001:10001" and last["workdir"] == "/work/repo"
    c.api.results.append(([(b"", None)], 124))
    assert sb.exec(["sleep", "99"], timeout_s=1, max_output_kb=1).timed_out
    c.api.results.append(([(b"ok", None)], 0))
    small = sb.exec(["echo"], timeout_s=1, max_output_kb=1)
    assert small.stdout == "ok" and not small.truncated


def test_clone_uses_extraheader_and_never_the_url_for_the_token() -> None:
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    creds = CloneCredentials(
        url="https://github.com/acme/web.git", username="x-access-token", token="ghs_T0K"
    )
    sb.clone(creds, "h" * 40, 50, extra_refs=["b" * 40])
    cmds = [e["cmd"] for e in c.api.execs]
    fetches = [cmd for cmd in cmds if "fetch" in cmd]
    b64 = base64.b64encode(b"x-access-token:ghs_T0K").decode()
    assert f"http.extraHeader=Authorization: Basic {b64}" in fetches[0]
    assert "https://github.com/acme/web.git" in fetches[0] and "--depth=50" in fetches[0]
    assert fetches[0][-1] == "h" * 40 and fetches[1][-1] == "b" * 40
    assert all("ghs_T0K" not in part for cmd in cmds for part in cmd)
    assert cmds[-1][-4:] == ["checkout", "-q", "--detach", "h" * 40]


def test_clone_tolerates_missing_base_ref() -> None:
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    c.api.results += [
        ([(b"", None)], 0),  # init
        ([(b"", None)], 0),  # fetch head
        ([(None, b"not our ref")], 128),  # fetch base (force-pushed away)
        ([(b"", None)], 0),  # checkout
    ]
    sb.clone(
        CloneCredentials(url="https://x/y.git", username="u", token="t"),
        "h" * 40,
        5,
        extra_refs=["b" * 40],
    )


def test_clone_failure_redacts_token() -> None:
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    b64 = base64.b64encode(b"u:SECRET").decode()
    c.api.results += [
        ([(b"", None)], 0),
        ([(None, f"fatal: auth {b64} SECRET failed".encode())], 128),
    ]
    with pytest.raises(CloneError) as exc:
        sb.clone(
            CloneCredentials(url="https://gitlab.com/g/p.git", username="u", token="SECRET"),
            "h" * 40,
            50,
        )
    assert "SECRET" not in str(exc.value) and b64 not in str(exc.value)


def test_file_url_is_uploaded_as_archive(tmp_path: Path) -> None:
    src = tmp_path / "checkout"
    (src / ".git").mkdir(parents=True)
    (src / "a.py").write_text("x = 1\n")
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    sb.clone(CloneCredentials(url=f"file://{src}", username="local", token=""), "h" * 40, 50)
    assert c.api.archive is not None
    path, data = c.api.archive
    assert path == "/work"
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        member = tar.getmember("repo/a.py")
        assert member.uid == 10001
    assert not any("fetch" in e["cmd"] for e in c.api.execs)
    assert c.api.execs[-1]["cmd"][-4:] == ["checkout", "-q", "--detach", "h" * 40]


def test_read_file_checks_path_and_symlinks() -> None:
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    with pytest.raises(UnsafePath):
        sb.read_file("../etc/passwd")
    c.api.results += [([(b"/work/repo/a.py\n", None)], 0), ([(b"x = 1\n", None)], 0)]
    assert sb.read_file("a.py") == "x = 1\n"
    assert c.api.execs[-1]["cmd"][4:] == ["head", "-c", "524288", "--", "/work/repo/a.py"]
    c.api.results += [([(b"/etc/passwd\n", None)], 0)]
    with pytest.raises(UnsafePath):
        sb.read_file("link")
    c.api.results += [([(b"", None)], 1)]
    assert sb.read_file("missing.py") == ""


def test_seal_disconnects_and_destroy_removes_with_volumes() -> None:
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    sb.seal()
    assert c.net.disconnected == ["c1"]
    sb.destroy()
    assert isinstance(sb, DockerSandbox)
    assert c.container is not None and c.container.removed == [{"force": True, "v": True}]


def test_peak_memory_reads_cgroup() -> None:
    c = FakeClient()
    sb = manager(c).create("j", mem_mb=768, cpus=1.0)
    c.api.results += [([(str(300 * 1024 * 1024).encode(), None)], 0), ([(b"", None)], 1)]
    assert sb.peak_memory_mb() == 300
    assert sb.peak_memory_mb() is None


def test_gc_removes_only_old_sandboxes() -> None:
    c = FakeClient()
    old = FakeContainer(id="old", labels={SANDBOX_LABEL: "1", f"{SANDBOX_LABEL}.created": "1000"})
    new = FakeContainer(id="new", labels={SANDBOX_LABEL: "1", f"{SANDBOX_LABEL}.created": "2900"})
    bad = FakeContainer(id="bad", labels={SANDBOX_LABEL: "1", f"{SANDBOX_LABEL}.created": "x"})
    c.listed = [old, new, bad]
    assert manager(c).gc_orphans(max_age_s=1800, now=3000.0) == 2
    assert old.removed and not new.removed and bad.removed
    assert c.list_kw == {"all": True, "filters": {"label": SANDBOX_LABEL}}


def test_factory_picks_backend(settings: Settings, tmp_path: Path) -> None:
    from app.sandbox.factory import build_sandbox_manager
    from app.sandbox.local import LocalSandboxManager

    local = build_sandbox_manager(
        settings.model_copy(
            update={"sandbox_backend": "local", "sandbox_local_tools_dir": str(tmp_path)}
        )
    )
    assert isinstance(local, LocalSandboxManager) and local.tools_dir == tmp_path
    # docker: the client is created lazily, so building the manager never touches the socket
    remote = build_sandbox_manager(settings)
    assert isinstance(remote, DockerSandboxManager)


def test_docker_manager_from_settings_reports_unreachable_proxy(settings: Settings) -> None:
    m = DockerSandboxManager.from_settings(settings)  # docker_host is tcp://127.0.0.1:1
    with pytest.raises(SandboxUnavailable):
        m.create("j", mem_mb=768, cpus=1.0)
