"""In-memory index over build_graph.py output (contract C1, spec §7.2)."""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Symbol:
    id: str
    kind: str
    name: str
    qualified_name: str
    path: str
    start_line: int
    end_line: int
    signature: str

    def ref(self) -> str:
        sig = f" — {self.signature}" if self.signature else ""
        return (
            f"{self.path}:{self.start_line}-{self.end_line} {self.kind} {self.qualified_name}{sig}"
        )


@dataclass(frozen=True, slots=True)
class Edge:
    src: str
    dst: str
    kind: str


@dataclass(frozen=True, slots=True)
class EntryPoint:
    """An externally reachable symbol (phase 6): HTTP route, CLI main, message handler."""

    symbol: str
    kind: str  # http | cli | message | server_action
    framework: str
    method: str | None
    route: str | None
    name: str
    path: str
    line: int
    auth: bool
    auth_evidence: str | None


@dataclass(frozen=True, slots=True)
class Sink:
    """A call into auth / crypto / exec / file / db / network code (phase 6)."""

    symbol: str
    category: str
    callee: str
    path: str
    line: int


def _opt(value: object) -> str | None:
    return None if value is None else str(value)[:200]


def _dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


class CodeGraph:
    """Name/path/edge lookups over one review's code graph; unknown ids are ignored."""

    def __init__(
        self,
        symbols: Iterable[Symbol],
        edges: Iterable[Edge],
        *,
        scope: str = "none",
        truncated: bool = False,
        entry_points: Iterable[EntryPoint] = (),
        sinks: Iterable[Sink] = (),
    ) -> None:
        self.scope, self.truncated = scope, truncated
        self._syms: dict[str, Symbol] = {s.id: s for s in symbols}
        self._by_name: dict[str, list[Symbol]] = defaultdict(list)
        self._by_path: dict[str, list[Symbol]] = defaultdict(list)
        for s in self._syms.values():
            if s.kind != "module":
                self._by_name[s.name].append(s)
                self._by_path[s.path].append(s)
        self._out: dict[str, list[Edge]] = defaultdict(list)
        self._in: dict[str, list[Edge]] = defaultdict(list)
        for e in edges:
            if e.src in self._syms and e.dst in self._syms:
                self._out[e.src].append(e)
                self._in[e.dst].append(e)
        self.entry_points = [ep for ep in entry_points if ep.symbol in self._syms]
        self.sinks = [x for x in sinks if x.symbol in self._syms]

    @classmethod
    def empty(cls) -> CodeGraph:
        return cls([], [])

    @classmethod
    def from_json(cls, data: object) -> CodeGraph:
        if not isinstance(data, dict) or data.get("version") != 1:
            return cls.empty()
        symbols: list[Symbol] = []
        for raw in _dicts(data.get("symbols")):
            try:
                symbols.append(
                    Symbol(
                        str(raw["id"]),
                        str(raw["kind"]),
                        str(raw["name"]),
                        str(raw.get("qualified_name") or raw["name"]),
                        str(raw["path"]),
                        int(raw["start_line"]),
                        int(raw["end_line"]),
                        str(raw.get("signature") or "")[:160],
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        # Edges reuse the symbols' id strings (and interned kinds): at the GRAPH_MAX_SYMBOLS cap
        # this halves the worker's resident size for the graph (spec §11.3, 256 MB worker).
        ids = {s.id: s.id for s in symbols}
        edges: list[Edge] = []
        for raw in _dicts(data.get("edges")):
            src, dst = ids.get(str(raw.get("from"))), ids.get(str(raw.get("to")))
            if src is None or dst is None or "kind" not in raw:
                continue
            edges.append(Edge(src, dst, sys.intern(str(raw["kind"]))))
        entry_points: list[EntryPoint] = []
        for raw in _dicts(data.get("entry_points")):
            try:
                entry_points.append(
                    EntryPoint(
                        str(raw["symbol"]),
                        str(raw["kind"]),
                        str(raw.get("framework") or ""),
                        _opt(raw.get("method")),
                        _opt(raw.get("route")),
                        str(raw.get("name") or "")[:200],
                        str(raw["path"]),
                        int(raw.get("line") or 0),
                        bool(raw.get("auth")),
                        _opt(raw.get("auth_evidence")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        sinks: list[Sink] = []
        for raw in _dicts(data.get("sinks")):
            try:
                sinks.append(
                    Sink(
                        ids.get(str(raw["symbol"]), str(raw["symbol"])),
                        sys.intern(str(raw["category"])),
                        str(raw.get("callee") or "")[:80],
                        str(raw["path"]),
                        int(raw.get("line") or 0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return cls(
            symbols,
            edges,
            scope=str(data.get("scope") or "none"),
            truncated=bool(data.get("truncated")),
            entry_points=entry_points,
            sinks=sinks,
        )

    def __len__(self) -> int:
        return len(self._syms)

    def symbol(self, symbol_id: str) -> Symbol | None:
        return self._syms.get(symbol_id)

    def incoming(self, symbol_id: str) -> list[Edge]:
        return list(self._in.get(symbol_id, ()))

    def outgoing(self, symbol_id: str) -> list[Edge]:
        return list(self._out.get(symbol_id, ()))

    def symbols_in_path(self, path: str) -> list[Symbol]:
        """Non-module symbols of ``path``."""
        return list(self._by_path.get(path, ()))

    def find_symbol(self, name: str, limit: int = 20) -> list[Symbol]:
        """Symbols named ``name`` (bare or qualified, e.g. ``Api.show``); modules excluded."""
        exact = [
            s
            for s in self._by_name.get(name.split(".")[-1], [])
            if s.qualified_name == name or s.name == name or s.qualified_name.endswith("." + name)
        ]
        return exact[:limit]

    def _walk(self, name: str, incoming: bool, limit: int) -> list[Symbol]:
        seen: dict[str, Symbol] = {}
        for target in self.find_symbol(name, limit=50):
            edges = self._in.get(target.id, []) if incoming else self._out.get(target.id, [])
            for e in edges:
                if e.kind == "calls":
                    other = self._syms[e.src if incoming else e.dst]
                    seen.setdefault(other.id, other)
        return list(seen.values())[:limit]

    def find_callers(self, name: str, limit: int = 20) -> list[Symbol]:
        return self._walk(name, True, limit)

    def find_callees(self, name: str, limit: int = 20) -> list[Symbol]:
        return self._walk(name, False, limit)

    def enclosing(self, path: str, line: int) -> Symbol | None:
        """The innermost non-module symbol containing ``line``."""
        inside = [s for s in self._by_path.get(path, []) if s.start_line <= line <= s.end_line]
        return min(inside, key=lambda s: s.end_line - s.start_line, default=None)

    def symbols_in_range(self, path: str, start: int, end: int) -> list[Symbol]:
        return [
            s for s in self._by_path.get(path, []) if s.start_line <= end and start <= s.end_line
        ]

    def related_files(self, path: str, limit: int = 20) -> list[str]:
        """Files this file imports and files importing it."""
        mid = f"{path}#module"
        out: dict[str, None] = {}
        for e in [*self._out.get(mid, []), *self._in.get(mid, [])]:
            if e.kind == "imports":
                other = self._syms[e.dst if e.src == mid else e.src].path
                if other != path:
                    out.setdefault(other)
        return list(out)[:limit]

    def neighborhood(self, paths: Sequence[str], limit_chars: int = 4000) -> str:
        """A compact one-line-per-file overview (symbols, callers, related files) for prompts."""
        lines: list[str] = []
        for p in paths:
            syms = self._by_path.get(p, [])[:8]
            callers = {c.qualified_name for s in syms for c in self.find_callers(s.name, limit=5)}
            rel = self.related_files(p, limit=5)
            lines.append(
                f"{p}: symbols={[s.qualified_name for s in syms]} "
                f"callers={sorted(callers)[:8]} related={rel}"
            )
        return "\n".join(lines)[:limit_chars]
