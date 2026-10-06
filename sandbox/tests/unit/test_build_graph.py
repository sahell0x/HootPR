import json
import subprocess
import sys
from pathlib import Path

import build_graph
import pytest
from build_graph import build

TOOLS = Path(__file__).resolve().parents[2] / "hootpr_tools"


def sym(g: dict, qualified: str) -> dict:
    return next(s for s in g["symbols"] if s["qualified_name"] == qualified)


def edges(g: dict, kind: str) -> set[tuple[str, str]]:
    ids = {s["id"]: s["qualified_name"] for s in g["symbols"]}
    return {(ids[e["from"]], ids[e["to"]]) for e in g["edges"] if e["kind"] == kind}


def test_python_symbols_calls_imports_inherits(polyglot: Path) -> None:
    g = build(polyglot, ["app/service.py"], 3000, 20000)
    assert g["version"] == 1 and g["scope"] == "full" and g["truncated"] is False
    show = sym(g, "UserService.show")
    assert show["kind"] == "method" and show["path"] == "app/service.py"
    assert show["signature"].startswith("def show(self, uid)")
    assert show["id"] == f"app/service.py#UserService.show@{show['start_line']}"
    assert ("UserService.show", "get_user") in edges(g, "calls")
    assert ("service", "db") in edges(g, "imports")
    assert ("UserService", "Base") in edges(g, "inherits")


def test_typescript_relative_import_and_calls(polyglot: Path) -> None:
    g = build(polyglot, ["web/api.ts"], 3000, 20000)
    assert sym(g, "Api.title")["kind"] == "method"
    assert ("Api.title", "slug") in edges(g, "calls")
    assert ("api", "util") in edges(g, "imports")


def test_go_import_resolves_package_directory(polyglot: Path) -> None:
    g = build(polyglot, ["go/main.go"], 3000, 20000)
    assert ("main", "Get") in edges(g, "calls")
    assert ("main", "store") in edges(g, "imports")


SNIPPETS = {
    "A.java": "class A { void f() { g(); } void g() {} }\n",
    "a.rs": "struct S;\nfn f() { g(); }\nfn g() {}\n",
    "a.rb": "class A\n  def f\n    g\n  end\nend\n",
    "a.php": "<?php\nfunction f() { g(); }\nfunction g() {}\n",
    "a.c": "int g(void) { return 1; }\nint f(void) { return g(); }\n",
    "a.cpp": "class A { public: int f(); };\nint g() { return 1; }\n",
    "A.cs": "class A { void F() { G(); } void G() {} }\n",
    "a.kt": "class A { fun f() { g() } }\nfun g() {}\n",
    "a.swift": "class A { func f() { g() } }\nfunc g() {}\n",
    "a.sh": "g() { echo 1; }\nf() { g; }\n",
    "a.js": "const g = () => 1;\nfunction f() { return g(); }\n",
    "a.tsx": "export function View(): JSX.Element { return <div />; }\n",
}


def test_covers_thirteen_languages() -> None:
    langs = {build_graph.EXT_LANG[Path(n).suffix] for n in SNIPPETS} | {"python", "typescript", "go"}
    assert len(langs) >= 13, sorted(langs)


def test_prefetch_lists_every_grammar(monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[list[str]] = []
    monkeypatch.setattr(build_graph, "_download", lambda langs: fetched.append(langs))
    assert build_graph.main(["--prefetch"]) == 0
    assert set(fetched[0]) == set(build_graph.EXT_LANG.values())


@pytest.mark.parametrize("name", sorted(SNIPPETS))
def test_every_supported_language_yields_symbols(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text(SNIPPETS[name])
    g = build(tmp_path, [name], 3000, 20000)
    kinds = {s["kind"] for s in g["symbols"] if s["path"] == name}
    assert kinds - {"module"}, f"no symbols for {name}: {g['errors']}"


def test_one_hop_scope_when_repo_is_big(polyglot: Path) -> None:
    g = build(polyglot, ["app/db.py"], 3, 20000)
    assert g["scope"] == "changed+1hop"
    paths = {f["path"] for f in g["files"]}
    assert {"app/db.py", "app/service.py"} <= paths  # changed + importer
    assert "web/util.ts" not in paths


def test_truncation_keeps_changed_symbols(polyglot: Path) -> None:
    g = build(polyglot, ["app/service.py"], 3000, 5)
    assert g["truncated"] is True and len(g["symbols"]) == 5
    assert all(s["path"] == "app/service.py" for s in g["symbols"])


def test_syntax_errors_are_reported_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n")
    g = build(tmp_path, ["bad.py", "missing.py"], 3000, 20000)
    assert g["errors"] and g["errors"][0]["path"] == "bad.py"


def test_cli_prints_json_and_rejects_bad_args(polyglot: Path) -> None:
    ok = subprocess.run(
        [sys.executable, str(TOOLS / "build_graph.py"), "--repo", str(polyglot), "--changed", "app/db.py"],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0 and json.loads(ok.stdout)["version"] == 1
    bad = subprocess.run([sys.executable, str(TOOLS / "build_graph.py")], capture_output=True, text=True)
    assert bad.returncode == 2
