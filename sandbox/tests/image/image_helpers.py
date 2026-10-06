"""Shared image-test helpers: the image name, its presence check and the production hardening flags."""

import os
import shutil
import subprocess
from pathlib import Path

IMAGE = os.environ.get("SANDBOX_IMAGE", "hootpr/sandbox:latest")


def _image_present() -> bool:
    if shutil.which("docker") is None:
        return False
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, text=True, check=False)
    return r.returncode == 0


# Same flags as DockerSandboxManager.create (backend/app/sandbox/docker.py), minus the egress network.
HARDENING = [
    "--read-only",
    "--tmpfs",
    "/tmp:rw,nosuid,nodev,size=64m",
    "--user",
    "10001:10001",
    "--security-opt",
    "no-new-privileges:true",
    "--cap-drop",
    "ALL",
    "--network",
    "none",
    "--memory",
    "768m",
    "--memory-swap",
    "768m",
    "--pids-limit",
    "256",
    "--cpus",
    "1.0",
]
ALL_TOOLS = (
    "semgrep,gitleaks,trivy,checkov,ruff,eslint,shellcheck,hadolint,actionlint,yamllint,markdownlint,golangci_lint"
)


def _readable(repo: Path) -> None:
    """pytest's tmp dirs are 0700; the sandbox user (uid 10001) must be able to read the bind mount."""
    for p in [repo, *repo.rglob("*")]:
        p.chmod(p.stat().st_mode | (0o755 if p.is_dir() else 0o644))
