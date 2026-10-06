import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "sandbox" / "hootpr_tools"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "polyglot"
sys.path.insert(0, str(TOOLS))
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=GIT_ENV
    ).stdout.strip()


@pytest.fixture
def polyglot(tmp_path: Path) -> Path:
    """The fixture as a git repo: commit 1 = everything but app/settings.py, commit 2 adds it."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    secret = (repo / "app" / "settings.py").read_text()
    (repo / "app" / "settings.py").unlink()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "app" / "settings.py").write_text(secret)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "head")
    return repo
