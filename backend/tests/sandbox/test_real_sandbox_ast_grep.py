"""Needs Docker + the hootpr/sandbox image (`make test-sandbox`): ast-grep instructions and the
ast-grep-essentials pack run inside the hardened, sealed sandbox (plan contract C4)."""

import os
from pathlib import Path

import docker
import pytest

from app.config.schema import HootPRConfig
from app.platforms.base import CloneCredentials
from app.review.ast_grep import run_ast_grep
from app.sandbox.base import sandbox_session
from app.sandbox.docker import DockerSandboxManager
from app.settings import Settings
from tests.helpers_git import make_git_repo

pytestmark = pytest.mark.sandbox
IMAGE = os.environ.get("SANDBOX_IMAGE", "hootpr/sandbox:latest")
RULE = {
    "id": "no-print",
    "language": "python",
    "message": "Use logging.",
    "rule": {"pattern": "print($$$A)"},
}


def test_ast_grep_instructions_and_essentials_in_real_sandbox(
    tmp_path: Path, settings: Settings
) -> None:
    repo = make_git_repo(
        tmp_path / "src",
        {"README.md": "x\n"},
        {"app.py": 'print("hi")\n'},
    )
    cfg = HootPRConfig.model_validate(
        {
            "reviews": {
                "ast_grep_instructions": [RULE],
                "tools": {"ast_grep": {"essential_rules": True}},
            }
        }
    )
    mgr = DockerSandboxManager(docker.from_env(), image=IMAGE, network="hootpr_sandbox_egress")
    with sandbox_session(mgr, "astgrep-test", mem_mb=768, cpus=1.0) as sb:
        sb.clone(
            CloneCredentials(url=f"file://{repo.path}", username="l", token=""),
            repo.head_sha,
            50,
            extra_refs=[repo.base_sha],
        )
        sb.seal()
        matches, why = run_ast_grep(sb, cfg, repo.base_sha, {"app.py": None}, settings)
    assert why is None, why
    assert [(m.rule_id, m.path, m.line) for m in matches] == [("no-print", "app.py", 1)]
