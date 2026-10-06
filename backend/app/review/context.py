"""Per-file context pack for planner/agents (spec §7 step 6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from app.config.schema import HootPRConfig
from app.platforms.base import FileDiff
from app.review.graph import CodeGraph, Symbol
from app.review.safety import untrusted
from app.review.stages.diff_filter import glob_match
from app.review.tool_results import StaticFinding, ToolResults

if TYPE_CHECKING:
    from app.review.ast_grep import AstGrepMatch

PATCH_MAX_CHARS = 12_000
OMITTED = "(diff omitted: context budget reached; inspect with read_file or shell)"


@dataclass(frozen=True)
class FileContext:
    path: str
    status: str
    additions: int
    deletions: int
    patch: str
    symbols: tuple[Symbol, ...]
    callers: tuple[Symbol, ...]
    callees: tuple[Symbol, ...]
    related_files: tuple[str, ...]
    static: tuple[StaticFinding, ...]
    instructions: tuple[str, ...]
    # ast-grep-rendered match messages (metavariables quote PR-head code): untrusted.
    ast_grep_notes: tuple[str, ...] = ()


def path_instructions_for(path: str, cfg: HootPRConfig) -> list[str]:
    return [pi.instructions for pi in cfg.reviews.path_instructions if glob_match(path, pi.path)]


def _uniq(symbols: Sequence[Symbol], limit: int) -> tuple[Symbol, ...]:
    seen: dict[str, Symbol] = {}
    for s in symbols:
        seen.setdefault(s.id, s)
    return tuple(list(seen.values())[:limit])


def build_file_context(
    f: FileDiff,
    graph: CodeGraph,
    tools: ToolResults,
    cfg: HootPRConfig,
    ast_grep: Sequence[AstGrepMatch] = (),
) -> FileContext:
    syms: list[Symbol] = []
    for h in f.hunks:
        syms += graph.symbols_in_range(f.path, h.new_start, h.new_start + max(h.new_count, 1) - 1)
    changed = _uniq(syms, 12)
    callers = _uniq([c for s in changed for c in graph.find_callers(s.name, limit=5)], 10)
    callees = _uniq([c for s in changed for c in graph.find_callees(s.name, limit=5)], 10)
    patch = f.patch or ""
    if len(patch) > PATCH_MAX_CHARS:
        patch = patch[:PATCH_MAX_CHARS] + "\n… (diff truncated; use read_file to see more)"
    return FileContext(
        f.path,
        f.status,
        f.additions,
        f.deletions,
        patch,
        changed,
        callers,
        callees,
        tuple(graph.related_files(f.path, limit=8)),
        tuple(tools.for_path(f.path)[:30]),
        (
            *path_instructions_for(f.path, cfg),
            *(f"AST-grep instruction {m.render()}" for m in ast_grep if m.path == f.path),
        ),
        tuple(n for m in ast_grep if m.path == f.path and (n := m.untrusted_note()) is not None),
    )


def render_file(ctx: FileContext) -> str:
    parts = [f"### FILE {ctx.path}", f"status: {ctx.status} (+{ctx.additions} -{ctx.deletions})"]
    if ctx.instructions:
        parts.append(
            "Instructions (from this repository's HootPR configuration):\n"
            + "\n".join(f"- {i}" for i in ctx.instructions)
        )
    parts.append(untrusted(f"diff:{ctx.path}", ctx.patch))
    if ctx.ast_grep_notes:
        parts.append(untrusted(f"ast-grep:{ctx.path}", "\n".join(ctx.ast_grep_notes)))
    if ctx.symbols or ctx.related_files:
        graph_lines = ["Changed symbols:", *(f"- {s.ref()}" for s in ctx.symbols)]
        if ctx.callers:
            graph_lines += ["Callers:", *(f"- {s.ref()}" for s in ctx.callers)]
        if ctx.callees:
            graph_lines += ["Callees:", *(f"- {s.ref()}" for s in ctx.callees)]
        if ctx.related_files:
            graph_lines += ["Related files: " + ", ".join(ctx.related_files)]
        parts.append(untrusted(f"graph:{ctx.path}", "\n".join(graph_lines)))
    if ctx.static:
        parts.append(untrusted(f"tools:{ctx.path}", "\n".join(s.render() for s in ctx.static)))
    return "\n".join(parts)


def render_pack(contexts: Sequence[FileContext], *, budget_chars: int) -> str:
    """Render every file; once the budget is used up, later files keep only their header/graph."""
    out: list[str] = []
    used = 0
    for ctx in contexts:
        block = render_file(ctx)
        if used + len(block) > budget_chars:
            block = render_file(replace(ctx, patch=OMITTED, static=ctx.static[:5]))
        out.append(block)
        used += len(block)
    return "\n\n".join(out)
