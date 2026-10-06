from app.review.graph import CodeGraph

DATA = {
    "version": 1,
    "scope": "full",
    "truncated": False,
    "files": [],
    "symbols": [
        {
            "id": "db.py#module",
            "kind": "module",
            "name": "db",
            "qualified_name": "db",
            "path": "db.py",
            "start_line": 1,
            "end_line": 30,
            "signature": "",
        },
        {
            "id": "db.py#get_user@4",
            "kind": "function",
            "name": "get_user",
            "qualified_name": "get_user",
            "path": "db.py",
            "start_line": 4,
            "end_line": 9,
            "signature": "def get_user(conn, uid):",
        },
        {
            "id": "api.py#module",
            "kind": "module",
            "name": "api",
            "qualified_name": "api",
            "path": "api.py",
            "start_line": 1,
            "end_line": 20,
            "signature": "",
        },
        {
            "id": "api.py#Api.show@7",
            "kind": "method",
            "name": "show",
            "qualified_name": "Api.show",
            "path": "api.py",
            "start_line": 7,
            "end_line": 12,
            "signature": "def show(self, uid):",
        },
        {"id": "bad"},
    ],
    "edges": [
        {"from": "api.py#Api.show@7", "to": "db.py#get_user@4", "kind": "calls"},
        {"from": "api.py#module", "to": "db.py#module", "kind": "imports"},
        {"from": "x", "to": "y", "kind": "calls"},
    ],
    "errors": [],
}


def test_queries() -> None:
    g = CodeGraph.from_json(DATA)
    assert len(g) == 4
    assert g.scope == "full" and g.truncated is False
    assert [s.qualified_name for s in g.find_symbol("get_user")] == ["get_user"]
    assert [s.qualified_name for s in g.find_symbol("Api.show")] == ["Api.show"]
    assert [s.qualified_name for s in g.find_callers("get_user")] == ["Api.show"]
    assert [s.qualified_name for s in g.find_callees("show")] == ["get_user"]
    assert g.enclosing("api.py", 8).qualified_name == "Api.show"  # type: ignore[union-attr]
    assert g.enclosing("api.py", 15) is None  # modules are never "enclosing"
    assert g.related_files("db.py") == ["api.py"]
    assert g.related_files("api.py") == ["db.py"]
    assert [s.name for s in g.symbols_in_range("db.py", 5, 5)] == ["get_user"]
    assert "Api.show" in g.neighborhood(["db.py"])
    assert (
        g.find_symbol("get_user")[0].ref()
        == "db.py:4-9 function get_user — def get_user(conn, uid):"
    )


def test_unknown_version_or_garbage_is_empty() -> None:
    assert len(CodeGraph.from_json({"version": 2})) == 0
    assert len(CodeGraph.from_json("nope")) == 0
    assert len(CodeGraph.from_json({"version": 1, "symbols": "x", "edges": [1, None]})) == 0
    assert CodeGraph.empty().find_callers("x") == []
