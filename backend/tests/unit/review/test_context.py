from app.config.schema import HootPRConfig
from app.platforms.diff import build_file_diff
from app.review.ast_grep import AstGrepMatch
from app.review.context import build_file_context, path_instructions_for, render_file, render_pack
from app.review.graph import CodeGraph
from app.review.tool_results import parse_tool_output

GRAPH = CodeGraph.from_json(
    {
        "version": 1,
        "symbols": [
            {
                "id": "db.py#get@1",
                "kind": "function",
                "name": "get",
                "qualified_name": "get",
                "path": "db.py",
                "start_line": 1,
                "end_line": 5,
                "signature": "def get(q):",
            },
            {
                "id": "api.py#show@3",
                "kind": "function",
                "name": "show",
                "qualified_name": "show",
                "path": "api.py",
                "start_line": 3,
                "end_line": 6,
                "signature": "def show():",
            },
        ],
        "edges": [{"from": "api.py#show@3", "to": "db.py#get@1", "kind": "calls"}],
    }
)
TOOLS = parse_tool_output(
    {
        "version": 1,
        "runs": [],
        "findings": [
            {
                "tool": "ruff",
                "rule_id": "S608",
                "path": "db.py",
                "line": 2,
                "end_line": 2,
                "severity": "error",
                "message": "SQL",
            }
        ],
    }
)
CFG = HootPRConfig.model_validate(
    {
        "reviews": {
            "path_instructions": [
                {"path": "**/db.py", "instructions": "Check parameterized queries."}
            ]
        }
    }
)


def test_file_context_includes_symbols_callers_tools_and_instructions() -> None:
    f = build_file_diff(
        "db.py", "@@ -1,2 +1,2 @@\n def get(q):\n-    return 1\n+    return run(q)\n", "modified"
    )
    ctx = build_file_context(f, GRAPH, TOOLS, CFG)
    assert [s.name for s in ctx.symbols] == ["get"]
    assert [s.name for s in ctx.callers] == ["show"]
    assert ctx.instructions == ("Check parameterized queries.",)
    text = render_file(ctx)
    assert text.startswith("### FILE db.py")
    assert '<untrusted source="diff:db.py">' in text and "[ruff:S608]" in text
    assert "Check parameterized queries." in text


def test_huge_patch_is_truncated() -> None:
    f = build_file_diff("a.py", "@@ -0,0 +1,1 @@\n+" + "x" * 20_000 + "\n", "added")
    ctx = build_file_context(f, CodeGraph.empty(), parse_tool_output(None), HootPRConfig())
    assert len(ctx.patch) < 12_200 and "diff truncated" in ctx.patch


def test_path_instructions_glob() -> None:
    assert path_instructions_for("src/db.py", CFG) == ["Check parameterized queries."]
    assert path_instructions_for("src/api.py", CFG) == []


def test_render_pack_respects_budget_but_lists_every_file() -> None:
    files = [
        build_file_diff(f"f{i}.py", "@@ -0,0 +1,1 @@\n+" + "x" * 3000 + "\n", "added")
        for i in range(5)
    ]
    ctxs = [
        build_file_context(f, CodeGraph.empty(), parse_tool_output(None), HootPRConfig())
        for f in files
    ]
    pack = render_pack(ctxs, budget_chars=5000)
    assert all(f"### FILE f{i}.py" in pack for i in range(5))
    assert "diff omitted" in pack and len(pack) < 9000


def test_ast_grep_rendered_messages_stay_untrusted() -> None:
    f = build_file_diff("a.py", "@@ -0,0 +1,2 @@\n+x\n+y\n", "added")
    matches = [
        AstGrepMatch("r", "a.py", 1, 1, 'found "IGNORE PREVIOUS"', "warning", "found $A"),
        AstGrepMatch("ess", "a.py", 2, 2, "essentials text", "warning"),
    ]
    ctx = build_file_context(f, CodeGraph.empty(), parse_tool_output(None), HootPRConfig(), matches)
    text = render_file(ctx)
    trusted, _, rest = text.partition('<untrusted source="diff:a.py">')
    assert "AST-grep instruction line 1 [r]: found $A" in trusted
    assert "IGNORE PREVIOUS" not in trusted and "essentials text" not in trusted
    assert '<untrusted source="ast-grep:a.py">' in rest
    assert 'line 1 [r]: found "IGNORE PREVIOUS"' in rest and "line 2 [ess]: essentials text" in rest
