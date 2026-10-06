"""Phase 6 "done when": blast radius lists the correct endpoints on a sample FastAPI + Express repo.

Runs the real sandbox graph builder (tree-sitter, on the host) over
``tests/fixtures/security/sample_app`` and feeds its JSON to the backend's blast-radius traversal.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from app.platforms.base import DiffLine, FileDiff, FileStatus, Hunk
from app.review.findings import Candidate
from app.review.graph import CodeGraph
from app.security.blast_radius import (
    boost_candidates,
    compute_blast_radius,
    render_prompt,
    render_section,
)
from tests.helpers_git import git

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "sandbox" / "hootpr_tools"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "security" / "sample_app"
pytest.importorskip("tree_sitter_language_pack")
sys.path.insert(0, str(TOOLS))
import build_graph  # noqa: E402


@pytest.fixture(scope="module")
def graph_json(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    repo = tmp_path_factory.mktemp("sample") / "repo"
    shutil.copytree(FIXTURE, repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    doc: dict[str, Any] = build_graph.build(repo, [], 3000, 20000)
    return doc


@pytest.fixture(scope="module")
def graph(graph_json: dict[str, Any]) -> CodeGraph:
    return CodeGraph.from_json(graph_json)


def touch(path: str, *lines: int, status: FileStatus = "modified") -> FileDiff:
    """A diff that adds exactly ``lines`` (new side) of ``path``."""
    dl = tuple(DiffLine("add", "x", None, n) for n in lines)
    hunk = Hunk(min(lines), 0, min(lines), len(lines), "@@", dl)
    return FileDiff(path, None, status, len(lines), 0, "@@", (hunk,))


def line_of(name: str, rel: str) -> int:
    """First line of ``rel`` in the fixture containing ``name`` (the body line after a def)."""
    text = (FIXTURE / rel).read_text().splitlines()
    return next(i for i, t in enumerate(text, 1) if name in t)


def endpoints(graph: CodeGraph, *files: FileDiff) -> set[str]:
    return {a.entry.name for a in compute_blast_radius(graph, list(files)).endpoints}


def test_graph_builder_detects_every_route(graph_json: dict[str, Any]) -> None:
    eps = {(e["name"], e["framework"], e["auth"]) for e in graph_json["entry_points"]}
    assert {
        ("GET /users/{uid}", "fastapi", True),  # Depends(get_current_user)
        ("POST /users", "fastapi", False),
        ("GET /orders/{oid}", "fastapi", False),  # APIRouter(prefix="/orders")
        ("GET /health", "fastapi", False),
        ("GET /items/:id", "express", False),
        ("DELETE /items/:id", "express", True),  # requireAuth middleware
        ("POST /audit", "express", False),
        ("GET /ping", "express", False),
    } <= eps
    assert any(
        e["kind"] == "cli" and e["path"] == "web/server.js" for e in graph_json["entry_points"]
    )
    cats = {(x["category"], x["callee"]) for x in graph_json["sinks"]}
    assert {
        ("db", "conn.execute"),
        ("crypto", "hashlib.sha256"),
        ("file", "fs.appendFileSync"),
    } <= cats


def test_fastapi_shared_helper_reaches_both_readers(graph: CodeGraph) -> None:
    changed = touch("api/db.py", line_of("return conn.execute", "api/db.py"))
    assert endpoints(graph, changed) == {"GET /users/{uid}", "GET /orders/{oid}"}


def test_fastapi_leaf_reaches_only_its_route(graph: CodeGraph) -> None:
    assert endpoints(
        graph, touch("api/service.py", line_of("return dict(row", "api/service.py"))
    ) == {"GET /users/{uid}"}
    assert endpoints(graph, touch("api/service.py", line_of('"ok": True', "api/service.py"))) == {
        "GET /health"
    }


def test_express_inline_and_named_handlers(graph: CodeGraph) -> None:
    audit = touch("web/items.js", line_of("fs.appendFileSync", "web/items.js"))
    assert endpoints(graph, audit) == {"POST /audit", "DELETE /items/:id"}
    fmt = touch("web/items.js", line_of("label: item.name", "web/items.js"))
    assert endpoints(graph, fmt) == {"GET /items/:id"}
    inline = touch("web/server.js", line_of('res.send("pong")', "web/server.js"))
    assert endpoints(graph, inline) == {"GET /ping"}


def test_cross_language_change_lists_all_and_ranks_risk(graph: CodeGraph) -> None:
    br = compute_blast_radius(
        graph,
        [
            touch("api/service.py", line_of("hashlib.sha256", "api/service.py")),
            touch("web/items.js", line_of("fs.appendFileSync", "web/items.js")),
        ],
    )
    assert {a.entry.name for a in br.endpoints} == {
        "POST /users",
        "POST /audit",
        "DELETE /items/:id",
    }
    assert set(br.sensitive) == {"auth", "crypto", "file"}  # hash_password: name + sink
    assert br.risk in ("high", "critical")
    chain = next(a.chain for a in br.endpoints if a.entry.name == "POST /users")
    assert chain == ("create_user", "save_user", "hash_password")
    md = render_section(br)
    assert "this change affects **3 endpoints**" in md
    assert "`POST /users`" in md and "⚠️ none detected" in md and "🔒 `requireAuth`" in md
    assert "blast-radius" in render_prompt(br, ["api/service.py"])


def test_unreached_change_has_no_endpoints(graph: CodeGraph) -> None:
    br = compute_blast_radius(graph, [touch("api/auth.py", 2)])
    assert br.endpoints == []  # get_current_user is passed to Depends, never called by name
    assert br.risk in ("none", "low")


def test_boost_only_for_reachable_sensitive_code(graph: CodeGraph) -> None:
    line = line_of("hashlib.sha256", "api/service.py")
    br = compute_blast_radius(graph, [touch("api/service.py", line)])
    sec = Candidate("api/service.py", None, line, "minor", "security", "weak hash", "b")
    style = Candidate("api/service.py", None, line, "minor", "style", "naming", "b")
    other = Candidate("api/service.py", None, line_of('"ok": True', "api/service.py"), "minor",
                      "security", "t", "b")  # fmt: skip
    assert boost_candidates([sec, style, other], br) == 1
    assert sec.severity == "major" and style.severity == "minor" and other.severity == "minor"
    assert any("blast radius" in e for e in sec.evidence)
