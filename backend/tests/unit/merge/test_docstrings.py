from app.merge.docstrings import docstring_coverage
from app.platforms.diff import build_file_diff
from app.review.graph import CodeGraph, Symbol

PY = '''import os


def documented(a,
               b):
    """Adds."""
    return a + b


def bare(x):
    # comment only
    return x


class Thing:
    def method(self):
        """Doc."""


def _private():
    return 1
'''

TS = """/** Adds two numbers. */
export function add(a: number, b: number) { return a + b }

export function sub(a: number, b: number) { return a - b }

// Multiplies.
@decorated
export class Mul {}
"""


def sym(path: str, kind: str, name: str, start: int, end: int) -> Symbol:
    return Symbol(f"{path}#{name}@{start}", kind, name, name, path, start, end, "")


def added(path: str, text: str):  # type: ignore[no-untyped-def]
    patch = f"@@ -0,0 +1,{len(text.splitlines())} @@\n" + "".join(
        f"+{ln}\n" for ln in text.splitlines()
    )
    return build_file_diff(path, patch, "added", None)


def test_python_and_ts_coverage() -> None:
    graph = CodeGraph(
        [
            sym("a.py", "function", "documented", 4, 7),
            sym("a.py", "function", "bare", 10, 12),
            sym("a.py", "class", "Thing", 15, 17),
            sym("a.py", "method", "method", 16, 17),
            sym("a.py", "function", "_private", 20, 21),
            sym("b.ts", "function", "add", 2, 2),
            sym("b.ts", "function", "sub", 4, 4),
            sym("b.ts", "class", "Mul", 8, 8),
            sym("tests/test_a.py", "function", "test_x", 1, 2),
        ],
        [],
    )
    files = [
        added("a.py", PY),
        added("b.ts", TS),
        added("tests/test_a.py", "def test_x():\n  pass\n"),
    ]
    texts = {"a.py": PY, "b.ts": TS}
    cov = docstring_coverage(graph, files, lambda p: texts[p])
    assert cov is not None
    # documented, method, add, Mul documented; bare, Thing, sub not
    assert (cov.total, cov.documented) == (7, 4)
    assert set(cov.missing) == {"a.py: bare", "a.py: Thing", "b.ts: sub"}
    assert round(cov.percent, 1) == 57.1


def test_only_symbols_touching_changed_lines_count() -> None:
    graph = CodeGraph(
        [sym("a.py", "function", "documented", 4, 7), sym("a.py", "function", "bare", 10, 12)], []
    )
    patch = "@@ -10,3 +10,3 @@\n def bare(x):\n-    # old\n+    # comment only\n     return x\n"
    f = build_file_diff("a.py", patch, "modified", None)
    cov = docstring_coverage(graph, [f], lambda p: PY)
    assert cov is not None and (cov.total, cov.documented) == (1, 0)


def test_empty_graph_is_none() -> None:
    assert docstring_coverage(CodeGraph.empty(), [], lambda p: "") is None
