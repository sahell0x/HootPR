"""Cross-repo breaking API changes (phase 7 done-when)."""
# ruff: noqa: E501

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.kb.cross_repo import api_changes, breaking_change_findings
from app.kb.linked import (
    LinkedGraph,
    LinkedRepoSpec,
    build_linked_graphs,
    clone_linked,
    dir_names,
)
from app.platforms.base import CloneCredentials, RepoRef
from app.review.graph import CodeGraph
from app.sandbox.base import sandbox_session
from app.sandbox.local import LocalSandboxManager
from app.settings import Settings
from tests.helpers_git import git, make_git_repo, write_stub_tools

TOOLS = Path(__file__).resolve().parents[4] / "sandbox" / "hootpr_tools"

USERS_V1 = "def get_user(uid):\n    return db.find(uid)\n\n\ndef list_users():\n    return []\n"
USERS_V2 = (
    "def get_user(uid, org_id):\n    return db.find(uid, org_id)\n\n\n"
    "def list_users():\n    return []\n"
)
SPEC = LinkedRepoSpec("billing", "acme/billing", RepoRef("github", "2", "acme/billing"))


def linked_graph(callee: str = "get_user") -> LinkedGraph:
    data: dict[str, Any] = {
        "version": 1,
        "symbols": [
            {
                "id": "invoice.py#charge@3",
                "kind": "function",
                "name": "charge",
                "qualified_name": "charge",
                "path": "invoice.py",
                "start_line": 3,
                "end_line": 6,
                "signature": "def charge(uid):",
            }
        ],
        "edges": [],
        "external_calls": [{"from": "invoice.py#charge@3", "name": callee}],
    }
    return LinkedGraph.from_json(SPEC, data)


def test_signature_change_used_by_linked_repo_is_flagged(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, {"core/users.py": USERS_V1}, {"core/users.py": USERS_V2})
    found = breaking_change_findings(repo.files, CodeGraph.empty(), [linked_graph()])
    assert len(found) == 1
    c = found[0]
    assert (c.path, c.end_line, c.severity, c.category) == ("core/users.py", 1, "major", "bug")
    assert c.source == "cross_repo"
    assert "acme/billing" in c.title and "get_user" in c.title
    assert "linked/billing/invoice.py:3-6" in c.body
    assert "def get_user(uid, org_id):" in c.body


def test_removed_function_is_flagged_and_anchored_in_hunk(tmp_path: Path) -> None:
    head = "def list_users():\n    return []\n"
    repo = make_git_repo(tmp_path, {"core/users.py": USERS_V1}, {"core/users.py": head})
    (ch,) = api_changes(repo.files, CodeGraph.empty())
    assert (ch.name, ch.kind) == ("get_user", "removed")
    found = breaking_change_findings(repo.files, CodeGraph.empty(), [linked_graph()])
    assert len(found) == 1 and found[0].end_line == ch.anchor and ch.anchor is not None


def test_body_only_change_or_unused_name_is_not_flagged(tmp_path: Path) -> None:
    body_only = USERS_V1.replace("db.find(uid)", "db.find_one(uid)")
    repo = make_git_repo(tmp_path, {"u.py": USERS_V1}, {"u.py": body_only})
    assert breaking_change_findings(repo.files, CodeGraph.empty(), [linked_graph()]) == []
    repo2 = make_git_repo(tmp_path / "b", {"u.py": USERS_V1}, {"u.py": USERS_V2})
    assert breaking_change_findings(repo2.files, CodeGraph.empty(), [linked_graph("other")]) == []
    assert breaking_change_findings(repo2.files, CodeGraph.empty(), []) == []


def test_private_and_generic_names_are_ignored(tmp_path: Path) -> None:
    base = "def _helper(a):\n    pass\n\n\ndef run(a):\n    pass\n"
    head = "def _helper(a, b):\n    pass\n\n\ndef run(a, b):\n    pass\n"
    repo = make_git_repo(tmp_path, {"m.py": base}, {"m.py": head})
    assert api_changes(repo.files, CodeGraph.empty()) == []


def test_js_and_go_signatures() -> None:
    from app.platforms.base import FileDiff
    from app.platforms.diff import parse_patch

    js = "@@ -1,2 +1,2 @@\n-export function fetchOrder(id) {\n+export function fetchOrder(id, opts) {\n   x\n"
    go = "@@ -1,2 +1,2 @@\n-func (s *Svc) GetOrder(id int) error {\n+func (s *Svc) GetOrder(ctx context.Context, id int) error {\n }\n"
    files = [
        FileDiff("a.ts", None, "modified", 1, 1, js, parse_patch(js)),
        FileDiff("b.go", None, "modified", 1, 1, go, parse_patch(go)),
    ]
    assert {(c.name, c.kind) for c in api_changes(files)} == {
        ("fetchOrder", "signature_changed"),
        ("GetOrder", "signature_changed"),
    }


def test_dir_names_dedupe() -> None:
    assert dir_names(["acme/api", "acme/web"]) == ["api", "web"]
    assert dir_names(["a/api", "b/api"]) == ["a-api", "b-api"]


@pytest.mark.skipif(
    importlib.util.find_spec("tree_sitter_language_pack") is None, reason="needs tree-sitter"
)
def test_linked_repo_clone_graph_and_breaking_change_end_to_end(
    tmp_path: Path, settings: Settings
) -> None:
    """Real build_graph.py over a real shallow clone in the local sandbox."""
    main = make_git_repo(
        tmp_path / "main", {"core/users.py": USERS_V1}, {"core/users.py": USERS_V2}
    )
    lib = tmp_path / "billing"
    lib.mkdir()
    git(lib, "init", "-q", "-b", "main")
    (lib / "invoice.py").write_text(
        "from core.users import get_user\n\n\ndef charge(uid):\n    u = get_user(uid)\n    return u\n"
    )
    git(lib, "add", "-A")
    git(lib, "commit", "-q", "-m", "init")

    class Platform:
        def clone_credentials(self, repo: RepoRef) -> CloneCredentials:
            return CloneCredentials(f"file://{lib}", "x", "")

    degraded: dict[str, Any] = {}
    with sandbox_session(LocalSandboxManager(), "linked", mem_mb=256, cpus=1) as sb:
        cloned = clone_linked(sb, Platform(), [SPEC], settings, degraded)  # type: ignore[arg-type]
        assert cloned == [SPEC] and not degraded
        dest = Path(sb.repo_dir).parent / "linked" / "billing"
        assert (dest / "invoice.py").is_file()
        # The real graph builder (host env: the local sandbox's minimal env has no grammar cache).
        out = subprocess.run(  # noqa: S603
            [sys.executable, str(TOOLS / "build_graph.py"), "--repo", str(dest), "--external-calls"],
            capture_output=True, text=True, timeout=120, check=True,
        )  # fmt: skip
        data = json.loads(out.stdout)
    graph = LinkedGraph.from_json(SPEC, data)
    assert [s.name for s in graph.callers_of("get_user")] == ["charge"]
    found = breaking_change_findings(main.files, CodeGraph.empty(), [graph])
    assert len(found) == 1 and "acme/billing" in found[0].title


def test_build_linked_graphs_runs_graph_tool_per_linked_repo(
    tmp_path: Path, settings: Settings
) -> None:
    graph = {
        "version": 1, "scope": "full", "truncated": False, "files": [], "edges": [], "errors": [],
        "symbols": [{"id": "i.py#charge@1", "kind": "function", "name": "charge",
                     "qualified_name": "charge", "path": "i.py", "start_line": 1, "end_line": 2}],
        "external_calls": [{"from": "i.py#charge@1", "name": "get_user"}],
    }  # fmt: skip
    tools = write_stub_tools(tmp_path / "tools", graph=graph)
    degraded: dict[str, Any] = {}
    with sandbox_session(LocalSandboxManager(tools), "g", mem_mb=256, cpus=1) as sb:
        (Path(sb.repo_dir).parent / "linked" / "billing").mkdir(parents=True)
        graphs = build_linked_graphs(sb, [SPEC], settings, degraded)
    assert not degraded
    assert [graphs[0].ref(s) for s in graphs[0].callers_of("core.get_user")] == [
        "[acme/billing] linked/billing/i.py:1-2 function charge"
    ]
