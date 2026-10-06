"""Pick the sandbox backend from settings (plan Q2)."""

from pathlib import Path

from app.sandbox.base import SandboxManager
from app.sandbox.local import LocalSandboxManager
from app.settings import Settings


def build_sandbox_manager(settings: Settings) -> SandboxManager:
    if settings.sandbox_backend == "local":
        tools = Path(settings.sandbox_local_tools_dir) if settings.sandbox_local_tools_dir else None
        return LocalSandboxManager(tools)
    from app.sandbox.docker import DockerSandboxManager

    return DockerSandboxManager.from_settings(settings)
