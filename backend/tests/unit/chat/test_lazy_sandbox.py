import pytest

from app.chat.sandbox import LazySandbox
from app.platforms.base import CloneCredentials
from app.settings import Settings
from tests.fakes.sandbox import FakeSandboxManager


def creds() -> CloneCredentials:
    return CloneCredentials("https://x/r.git", "u", "t")


def test_lazy_sandbox_creates_on_first_use_and_destroys(settings: Settings) -> None:
    mgr = FakeSandboxManager()
    lazy = LazySandbox(mgr, "chat-1", creds, "h" * 40, settings)
    assert not lazy.created and mgr.created == []
    assert lazy.peak_memory_mb() is None
    lazy.destroy()  # no-op
    lazy.read_file("a.py")
    [sb] = mgr.created
    assert lazy.created and sb.cloned == ("https://x/r.git", "h" * 40) and sb.sealed
    lazy.shell("rg x", timeout_s=5, max_output_kb=4)
    assert len(mgr.created) == 1
    lazy.destroy()
    assert sb.destroyed


def test_failed_clone_still_destroys_the_container(settings: Settings) -> None:
    mgr = FakeSandboxManager()

    def bad() -> CloneCredentials:
        raise RuntimeError("no token")

    lazy = LazySandbox(mgr, "chat-2", bad, "h" * 40, settings)
    with pytest.raises(RuntimeError):
        lazy.exec(["ls"], timeout_s=5, max_output_kb=4)
    lazy.destroy()
    [sb] = mgr.created
    assert sb.destroyed


def test_failed_clone_is_not_retried(settings: Settings) -> None:
    mgr = FakeSandboxManager()
    calls: list[int] = []

    def bad() -> CloneCredentials:
        calls.append(1)
        raise RuntimeError("no token")

    lazy = LazySandbox(mgr, "chat-3", bad, "h" * 40, settings)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            lazy.read_file("a.py")
    assert len(calls) == 1 and len(mgr.created) == 1
