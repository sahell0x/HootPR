"""Docstring coverage of the changed code, from the review's code graph (spec §10.2).

Counted: functions, methods, classes, structs and interfaces whose line range overlaps an added
line (every symbol of an added file). Private (``_name``) symbols and test files are skipped, like
most docstring linters. A symbol is documented when:
- Python: the first statement after the signature is a string literal;
- other languages: the line right above it (after decorators/annotations) is a doc comment
  (``/** … */``, ``///``, ``//``, ``#``, ``--``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.config.schema import HootPRConfig
from app.platforms.base import FileDiff
from app.review.graph import CodeGraph, Symbol
from app.sandbox.base import Sandbox

COUNTED_KINDS = frozenset({"function", "method", "class", "struct", "interface"})
MAX_FILES = 100
MAX_LISTED = 10
SIGNATURE_MAX_LINES = 30
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.\w+$|\.(spec|test)\.\w+$"
)
_PY_STRING = re.compile(r"""^[rRuUbBfF]{0,2}("{3}|'{3}|"|')""")
_DOC_COMMENT = ("/**", "/*", "*", "*/", "///", "//!", "//", "#", "--", "%")


@dataclass(frozen=True)
class DocstringCoverage:
    total: int
    documented: int
    missing: tuple[str, ...] = field(default=())  # "path: qualified_name", at most MAX_LISTED

    @property
    def percent(self) -> float:
        return 100.0 if self.total == 0 else 100.0 * self.documented / self.total


def _python_documented(lines: list[str], start: int) -> bool:
    i = start - 1
    end = min(len(lines), i + SIGNATURE_MAX_LINES)
    while i < end:
        code = lines[i].split("#", 1)[0].rstrip()
        i += 1
        if code.endswith(":"):
            break
    else:
        return False
    while i < len(lines):
        s = lines[i].strip()
        if s and not s.startswith("#"):
            return bool(_PY_STRING.match(s))
        i += 1
    return False


def _comment_documented(lines: list[str], start: int) -> bool:
    i = start - 2
    while i >= 0 and lines[i].strip().startswith(("@", "#[")):  # decorators / attributes
        i -= 1
    if i < 0:
        return False
    s = lines[i].strip()
    return bool(s) and s.startswith(_DOC_COMMENT)


def is_documented(text: str, sym: Symbol) -> bool:
    lines = text.splitlines()
    if sym.start_line < 1 or sym.start_line > len(lines):
        return False
    if sym.path.endswith((".py", ".pyi")):
        return _python_documented(lines, sym.start_line)
    return _comment_documented(lines, sym.start_line)


def _changed_symbols(graph: CodeGraph, f: FileDiff) -> list[Symbol]:
    syms = [
        s
        for s in graph.symbols_in_range(f.path, 1, 10**9)
        if s.kind in COUNTED_KINDS and not s.name.startswith("_")
    ]
    if f.status == "added":
        return syms
    changed = f.changed_new_lines()
    return [s for s in syms if any(s.start_line <= ln <= s.end_line for ln in changed)]


def docstring_coverage(
    graph: CodeGraph, files: Sequence[FileDiff], read: Callable[[str], str]
) -> DocstringCoverage | None:
    """``None`` when the graph is empty (unavailable): the check is then inconclusive."""
    if len(graph) == 0:
        return None
    total = documented = 0
    missing: list[str] = []
    for f in files[:MAX_FILES]:
        if f.status == "removed" or _TEST_PATH.search(f.path):
            continue
        syms = _changed_symbols(graph, f)
        if not syms:
            continue
        try:
            text = read(f.path)
        except Exception:  # noqa: S112 - an unreadable file only drops out of the count
            continue
        for s in syms:
            total += 1
            if is_documented(text, s):
                documented += 1
            elif len(missing) < MAX_LISTED:
                missing.append(f"{f.path}: {s.qualified_name}")
    return DocstringCoverage(total, documented, tuple(missing))


def maybe_docstring_coverage(
    cfg: HootPRConfig,
    graph: CodeGraph,
    files: Sequence[FileDiff],
    sb: Sandbox,
    degraded: dict[str, Any],
) -> DocstringCoverage | None:
    """The engine's hook: only when the docstring check is on; never fails the review."""
    if cfg.reviews.pre_merge_checks.docstrings.mode == "off":
        return None
    try:
        return docstring_coverage(graph, files, lambda p: sb.read_file(p, max_kb=256))
    except Exception:
        degraded["docstring_coverage"] = "unavailable"
        return None
