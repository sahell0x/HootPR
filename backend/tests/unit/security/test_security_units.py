"""Phase 6 units: surface diff vs a stored map, command parsing, report hardening/rendering."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.chat.commands import parse_comment
from app.chat.identity import BotIdentity
from app.models import SecurityScan
from app.platforms.base import DiffLine, FileDiff, Hunk
from app.review.graph import CodeGraph, EntryPoint, Symbol
from app.security.blast_radius import compute_blast_radius, render_section
from app.security.jobs import clean_report, key_files, render_report_comment, surface_summary
from app.security.schemas import SecurityReport, SecurityRisk

ID = BotIdentity(frozenset({"hootpr[bot]"}), frozenset({"hootpr", "hootpr[bot]"}))


def _sym(path: str, name: str, start: int, end: int, kind: str = "function") -> Symbol:
    return Symbol(f"{path}#{name}@{start}", kind, name, name, path, start, end, "")


def _ep(sym: Symbol, name: str, auth: bool) -> EntryPoint:
    return EntryPoint(
        sym.id,
        "http",
        "fastapi",
        name.split()[0],
        name.split()[1],
        name,
        sym.path,
        sym.start_line,
        auth,
        "Depends(user)" if auth else None,
    )


def _diff(path: str, *lines: int) -> FileDiff:
    dl = tuple(DiffLine("add", "x", None, n) for n in lines)
    return FileDiff(path, None, "modified", len(lines), 0, "@@", (Hunk(1, 0, 1, 1, "@@", dl),))


def test_security_review_command_is_recognized() -> None:
    p = parse_comment("@hootpr security review", ID)
    assert p.command == "security_review"


def test_surface_changes_against_stored_map() -> None:
    mod = Symbol("api.py#module", "module", "api", "api", "api.py", 1, 40, "")
    a = _sym("api.py", "admin", 5, 8)
    b = _sym("api.py", "users", 10, 14)
    graph = CodeGraph(
        [mod, a, b],
        [],
        scope="full",
        entry_points=[_ep(a, "POST /admin", False), _ep(b, "GET /users", False)],
    )
    baseline = (
        {"kind": "http", "name": "GET /users", "path": "api.py", "line": 10, "auth": True},
        {"kind": "http", "name": "GET /old", "path": "api.py", "line": 20, "auth": False},
        {"kind": "http", "name": "GET /elsewhere", "path": "other.py", "line": 1, "auth": False},
    )
    br = compute_blast_radius(graph, [_diff("api.py", 6)], baseline=baseline)
    got = {(c.change, c.name) for c in br.surface_changes}
    assert got == {
        ("added", "POST /admin"),
        ("removed", "GET /old"),
        ("auth_removed", "GET /users"),
    }
    md = render_section(br)
    assert "Attack surface changes" in md and "no longer has an auth check" in md
    assert "no auth check detected" in md


def test_without_baseline_new_means_added_line() -> None:
    mod = Symbol("api.py#module", "module", "api", "api", "api.py", 1, 40, "")
    a = _sym("api.py", "admin", 5, 8)
    graph = CodeGraph([mod, a], [], scope="full", entry_points=[_ep(a, "POST /admin", True)])
    assert [
        c.change for c in compute_blast_radius(graph, [_diff("api.py", 5)]).surface_changes
    ] == ["added"]
    assert compute_blast_radius(graph, [_diff("api.py", 7)]).surface_changes == []


def test_route_names_cannot_break_markdown() -> None:
    mod = Symbol("x.py#module", "module", "x", "x", "x.py", 1, 40, "")
    a = _sym("x.py", "h", 5, 8)
    graph = CodeGraph([mod, a], [], entry_points=[_ep(a, "GET /a`|@admin", False)])
    md = render_section(compute_blast_radius(graph, [_diff("x.py", 6)]))
    assert "`GET /a'\\|@admin`" in md


SURFACE = {
    "stats": {
        "http_endpoints": 3,
        "unauthenticated_endpoints": 1,
        "entry_points": 4,
        "outbound_calls": 2,
        "secrets": 1,
        "iac_findings": 2,
    },
    "entry_points": [
        {"kind": "http", "path": "a.py", "auth": True},
        {"kind": "http", "path": "b.py", "auth": False},
        {"kind": "cli", "path": "c.py", "auth": False},
    ],
    "sinks": {"examples": {"auth": [{"path": "auth.py"}]}},
    "iac": [{"path": "main.tf"}],
    "secrets": [{"path": ".env"}],
}


def test_key_files_prioritize_unauthenticated_routes() -> None:
    assert key_files(SURFACE) == ["b.py", "a.py", "auth.py", "main.tf", "c.py"]
    assert "3 HTTP endpoints (1 without detected auth)" in surface_summary(SURFACE)


def test_report_is_hardened_and_rendered() -> None:
    raw = SecurityReport(
        summary="Mostly fine. See https://evil.example/x @everyone",
        overall_risk="high",
        risks=[
            SecurityRisk(
                title="Low thing",
                severity="low",
                category="config",
                description="d",
                affected=["x"],
                recommendation="r",
            ),
            SecurityRisk(
                title="Unauthenticated admin <script>",
                severity="critical",
                category="authorization",
                description="POST /admin has no auth",
                affected=["POST /admin"],
                recommendation="Add Depends(admin)",
            ),
        ],
        strengths=["Uses parameterized queries"],
    )
    rep = clean_report(raw, "github.com")
    assert rep.risks[0].severity == "critical"
    assert "evil.example" not in rep.summary and "<script>" not in rep.risks[0].title
    scan = SecurityScan(
        id=uuid4(), branch="main", commit_sha="abcdef1234", summary="", credits_charged=Decimal("3")
    )
    body = render_report_comment(scan, rep, SURFACE, "https://app/o/x/security")
    assert body.startswith(f"<!-- hootpr:security:{scan.id} -->")
    assert "Overall risk: 🟠 high" in body and "Credits charged: 3" in body
    assert "`POST /admin`" in body
