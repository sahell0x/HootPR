"""Blast radius of a pull request (spec §10.3).

From the symbols a PR changes, a reverse traversal of the code graph (``calls``/``references``
edges) finds the entry points that can reach them: HTTP routes, CLI mains, message handlers and
server actions detected by ``build_graph.py``. The result feeds the walkthrough ("this change
affects N endpoints"), the agents' context packs and a one-level severity boost for security/bug
findings inside changed code that touches auth / crypto / IO sinks and is externally reachable.

Everything here is pure (graph + diff in, dataclasses out) and best effort: names are resolved
by the graph builder without type information, so the traversal can over- or under-reach.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.platforms.base import FileDiff
from app.review.findings import Candidate, Severity
from app.review.graph import CodeGraph, EntryPoint, Symbol
from app.review.safety import untrusted

Risk = Literal["none", "low", "medium", "high", "critical"]
SurfaceChangeKind = Literal["added", "removed", "auth_removed", "auth_added"]
MAX_DEPTH = 8
MAX_NODES = 5000
MAX_LISTED = 25
MAX_SURFACE_CHANGES = 20
TRAVERSED_EDGES = frozenset({"calls", "references"})
# Categories that make a change security-sensitive (auth / crypto / IO sinks).
SENSITIVE_CATEGORIES = ("auth", "crypto", "exec", "file", "db", "network")
HIGH_IMPACT = frozenset({"auth", "crypto", "exec"})
BOOST_FINDING_CATEGORIES = frozenset({"security", "bug"})
_BUMP: dict[str, Severity] = {"nitpick": "minor", "minor": "major", "major": "critical"}
RISK_ICON: dict[str, str] = {
    "none": "⚪",
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "critical": "🔴",
}
KIND_LABEL = {
    "http": "HTTP endpoint",
    "cli": "CLI entry point",
    "message": "message handler",
    "server_action": "server action",
}
FRAMEWORK_LABEL = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "django-rest": "Django REST",
    "express": "Express",
    "nextjs": "Next.js",
    "spring": "Spring",
    "gin": "Gin",
    "echo": "Echo",
    "chi": "chi",
    "fiber": "Fiber",
    "net/http": "net/http",
    "koa": "Koa",
    "fastify": "Fastify",
    "hono": "Hono",
    "aiohttp": "aiohttp",
}
_AUTH_NAME = re.compile(
    r"(?i)(authenticat|authoriz|login|logout|password|passwd|credential|session|permission|jwt|"
    r"token|oauth|saml|csrf|acl|rbac)"
)
_CRYPTO_NAME = re.compile(
    r"(?i)(encrypt|decrypt|cipher|hash|hmac|signature|crypto|nonce|salt|keypair|private_key)"
)


def sensitive_name(name: str) -> str | None:
    if _AUTH_NAME.search(name):
        return "auth"
    if _CRYPTO_NAME.search(name):
        return "crypto"
    return None


@dataclass(frozen=True)
class AffectedEntry:
    entry: EntryPoint
    depth: int
    chain: tuple[str, ...]  # handler → … → changed symbol (qualified names)
    changed_path: str  # file of the changed symbol this entry reaches


@dataclass(frozen=True)
class ChangedSymbol:
    symbol: Symbol
    sensitive: tuple[str, ...]  # sink categories touched by this symbol (incl. its own name)


@dataclass(frozen=True)
class SurfaceChange:
    change: SurfaceChangeKind
    kind: str
    name: str
    path: str
    line: int
    auth: bool


@dataclass
class BlastRadius:
    changed: list[ChangedSymbol]
    affected: list[AffectedEntry]
    sensitive: dict[str, list[str]]  # category -> example callees / symbol names
    risk: Risk
    partial: bool
    surface_changes: list[SurfaceChange] = field(default_factory=list)
    # (path, start, end) of changed symbols that touch a sensitive category.
    boosted_ranges: tuple[tuple[str, int, int], ...] = ()

    @property
    def endpoints(self) -> list[AffectedEntry]:
        return [a for a in self.affected if a.entry.kind == "http"]

    @property
    def empty(self) -> bool:
        return not self.affected and not self.sensitive and not self.surface_changes

    def summary(self) -> dict[str, Any]:
        """Compact JSON for traces / the review row."""
        return {
            "risk": self.risk,
            "endpoints": [a.entry.name for a in self.endpoints][:MAX_LISTED],
            "entry_points": len(self.affected),
            "sensitive": sorted(self.sensitive),
            "partial": self.partial,
            "surface_changes": len(self.surface_changes),
        }


# --- traversal ------------------------------------------------------------------------------


def _parent(graph: CodeGraph, sym: Symbol) -> Symbol | None:
    """The smallest non-module symbol strictly containing ``sym`` (its class, for a method)."""
    best: Symbol | None = None
    for s in graph.symbols_in_path(sym.path):
        if s.id == sym.id or s.kind in ("module", "entry"):
            continue
        inside = s.start_line <= sym.start_line and sym.end_line <= s.end_line
        if inside and (
            best is None or (s.end_line - s.start_line) < (best.end_line - best.start_line)
        ):
            best = s
    return best


def _changed_lines(f: FileDiff) -> set[int]:
    lines = f.changed_new_lines()
    if not lines:  # pure deletions: the hunk position on the new side
        lines = {max(1, h.new_start) for h in f.hunks}
    return lines


def changed_symbols(graph: CodeGraph, files: Sequence[FileDiff]) -> list[Symbol]:
    """Innermost symbols containing a changed line; a decorator line maps to the def below."""
    out: dict[str, Symbol] = {}
    for f in files:
        if f.status == "removed":
            continue
        syms = graph.symbols_in_path(f.path)
        for line in sorted(_changed_lines(f)):
            sym = graph.enclosing(f.path, line)
            if sym is None:
                below = [s for s in syms if 0 < s.start_line - line <= 3]
                sym = min(below, key=lambda s: s.start_line, default=None)
            if sym is None:
                sym = graph.symbol(f"{f.path}#module")
            if sym is not None:
                out.setdefault(sym.id, sym)
    return list(out.values())


def _risk(n: int, sens: set[str], unauth_http: bool) -> Risk:
    if n == 0:
        return "low" if sens else "none"
    risk: Risk = "low"
    if n >= 3 or sens:
        risk = "medium"
    if n >= 10 or (sens & HIGH_IMPACT) or (sens and unauth_http):
        risk = "high"
    if unauth_http and ("exec" in sens or ((sens & {"auth", "crypto"}) and n >= 3)):
        risk = "critical"
    return risk


def compute_blast_radius(
    graph: CodeGraph,
    files: Sequence[FileDiff],
    *,
    baseline: Sequence[Mapping[str, Any]] | None = None,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> BlastRadius:
    roots = changed_symbols(graph, files)
    by_symbol: dict[str, list[EntryPoint]] = defaultdict(list)
    for ep in graph.entry_points:
        by_symbol[ep.symbol].append(ep)
    # Callers of a class-based handler reach it through the class: an entry on a class, or a
    # class referenced by a synthetic registration (``path("x/", View.as_view())``).
    handler_classes = {sid for sid in by_symbol if (s := graph.symbol(sid)) and s.kind == "class"}
    for ep in graph.entry_points:
        for e in graph.outgoing(ep.symbol):
            target = graph.symbol(e.dst)
            if target is not None and target.kind == "class":
                handler_classes.add(target.id)

    parent: dict[str, str | None] = {s.id: None for s in roots}
    depth: dict[str, int] = {s.id: 0 for s in roots}
    queue: deque[str] = deque(s.id for s in roots)
    partial = graph.truncated or graph.scope not in ("full",)
    found: dict[tuple[str, str], AffectedEntry] = {}

    def chain(sid: str) -> tuple[tuple[str, ...], str]:
        names: list[str] = []
        cur: str | None = sid
        last = sid
        while cur is not None and len(names) < max_depth + 2:
            sym = graph.symbol(cur)
            if sym is not None and sym.kind != "entry":
                names.append(sym.qualified_name)
            last = cur
            cur = parent.get(cur)
        root = graph.symbol(last)
        return tuple(names), (root.path if root is not None else "")

    while queue:
        sid = queue.popleft()
        d = depth[sid]
        for ep in by_symbol.get(sid, ()):
            key = (ep.symbol, ep.name)
            if key not in found:
                names, root_path = chain(sid)
                found[key] = AffectedEntry(ep, d, names, root_path)
        sym = graph.symbol(sid)
        if sym is None or sym.kind == "module" or d >= max_depth:
            continue
        preds = [e.src for e in graph.incoming(sid) if e.kind in TRAVERSED_EDGES]
        if sym.kind == "method":
            cls = _parent(graph, sym)
            if cls is not None and cls.id in handler_classes:
                preds.append(cls.id)
        for p in preds:
            if p not in parent:
                parent[p], depth[p] = sid, d + 1
                queue.append(p)
        if len(parent) >= max_nodes:
            partial = True
            break

    changed_ids = {s.id for s in roots}
    sens_by_symbol: dict[str, set[str]] = defaultdict(set)
    sensitive: dict[str, list[str]] = {}
    for x in graph.sinks:
        if x.symbol in changed_ids:
            sens_by_symbol[x.symbol].add(x.category)
            examples = sensitive.setdefault(x.category, [])
            if x.callee and x.callee not in examples and len(examples) < 3:
                examples.append(x.callee)
    for s in roots:
        if s.kind in ("module", "entry"):
            continue
        cat = sensitive_name(s.name)
        if cat:
            sens_by_symbol[s.id].add(cat)
            examples = sensitive.setdefault(cat, [])
            if s.name not in examples and len(examples) < 3:
                examples.append(s.name)
    changed = [
        ChangedSymbol(s, tuple(c for c in SENSITIVE_CATEGORIES if c in sens_by_symbol[s.id]))
        for s in roots
    ]
    affected = sorted(
        found.values(), key=lambda a: (a.entry.kind != "http", a.depth, a.entry.path, a.entry.line)
    )
    unauth_http = any(a.entry.kind == "http" and not a.entry.auth for a in affected)
    risk = _risk(len(affected), set(sensitive), unauth_http)
    boosted = tuple(
        (c.symbol.path, c.symbol.start_line, c.symbol.end_line)
        for c in changed
        if c.sensitive and c.symbol.kind != "module"
    )
    return BlastRadius(
        changed=changed,
        affected=affected,
        sensitive={c: sensitive[c] for c in SENSITIVE_CATEGORIES if c in sensitive},
        risk=risk,
        partial=partial,
        surface_changes=surface_changes(graph, files, baseline),
        boosted_ranges=boosted,
    )


# --- attack surface diff --------------------------------------------------------------------


def _key(kind: str, name: str, path: str) -> tuple[str, str, str]:
    return (path, kind, name)


def surface_changes(
    graph: CodeGraph, files: Sequence[FileDiff], baseline: Sequence[Mapping[str, Any]] | None
) -> list[SurfaceChange]:
    """Entry points this PR adds, removes, or whose auth check changes.

    With a stored attack surface map (``baseline``: its ``entry_points``) the comparison is
    exact for the changed files; without one, "added" means registered on an added line."""
    changed_paths = {f.path for f in files}
    removed_paths = {f.path for f in files if f.status == "removed"}
    removed_paths |= {f.old_path for f in files if f.status == "renamed" and f.old_path}
    parsed = {p for p in changed_paths if graph.symbol(f"{p}#module") is not None}
    head = {
        _key(ep.kind, ep.name, ep.path): ep for ep in graph.entry_points if ep.path in changed_paths
    }
    out: list[SurfaceChange] = []
    if baseline is None:
        added_lines = {f.path: f.changed_new_lines() for f in files}
        for ep in head.values():
            sym = graph.symbol(ep.symbol)
            start = sym.start_line if sym is not None else ep.line
            file_added = next((f.status == "added" for f in files if f.path == ep.path), False)
            if file_added or start in added_lines.get(ep.path, set()):
                out.append(SurfaceChange("added", ep.kind, ep.name, ep.path, ep.line, ep.auth))
        return out[:MAX_SURFACE_CHANGES]
    base: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for raw in baseline:
        try:
            k = _key(str(raw["kind"]), str(raw["name"]), str(raw["path"]))
        except KeyError:
            continue
        if k[0] in changed_paths or k[0] in removed_paths:
            base.setdefault(k, raw)
    for k, ep in head.items():
        old = base.get(k)
        if old is None:
            out.append(SurfaceChange("added", ep.kind, ep.name, ep.path, ep.line, ep.auth))
        elif bool(old.get("auth")) and not ep.auth:
            out.append(SurfaceChange("auth_removed", ep.kind, ep.name, ep.path, ep.line, False))
        elif not bool(old.get("auth")) and ep.auth:
            out.append(SurfaceChange("auth_added", ep.kind, ep.name, ep.path, ep.line, True))
    for k, old in base.items():
        path = k[0]
        if k in head or (path not in parsed and path not in removed_paths):
            continue  # a file the graph could not parse proves nothing
        out.append(
            SurfaceChange(
                "removed", k[1], k[2], path, int(old.get("line") or 0), bool(old.get("auth"))
            )
        )
    order = {"auth_removed": 0, "added": 1, "removed": 2, "auth_added": 3}
    out.sort(key=lambda c: (order[c.change], c.path, c.line))
    return out[:MAX_SURFACE_CHANGES]


# --- severity boost ---------------------------------------------------------------------------


def boost_candidates(cands: Iterable[Candidate], br: BlastRadius | None) -> int:
    """Raise security/bug findings one level when they sit in changed code that touches a
    sensitive sink and is reachable from at least one entry point. Returns how many moved."""
    if br is None or not br.affected or not br.boosted_ranges:
        return 0
    n = 0
    names = ", ".join(br.sensitive) or "sensitive code"
    for c in cands:
        if not c.alive or c.category not in BOOST_FINDING_CATEGORIES or c.severity == "critical":
            continue
        hit = any(p == c.path and s <= c.end_line and c.start <= e for p, s, e in br.boosted_ranges)
        if not hit:
            continue
        c.severity = _BUMP[c.severity]
        c.evidence = [
            *c.evidence,
            f"blast radius: reachable from {len(br.affected)} entry point(s); touches {names}",
        ]
        n += 1
    return n


# --- rendering ------------------------------------------------------------------------------


def _code(text: str, n: int = 80) -> str:
    one = " ".join(text.split()).replace("`", "'").replace("|", "\\|")
    return "`" + (one[: n - 1] + "…" if len(one) > n else one) + "`"


def _where(ep: EntryPoint) -> str:
    return _code(f"{ep.path}:{ep.line}", 120)


def _label(ep: EntryPoint) -> str:
    fw = FRAMEWORK_LABEL.get(ep.framework, ep.framework)
    base = {"http": "route", "cli": "CLI", "message": "handler", "server_action": "action"}
    return f"{fw} {base.get(ep.kind, ep.kind)}".strip()


def _count_phrase(n: int, kind: str) -> str:
    label = KIND_LABEL.get(kind, kind)
    return f"{n} {label}{'' if n == 1 else 's'}"


def render_section(br: BlastRadius | None) -> str:
    """The walkthrough's "Blast radius" section; ``""`` when there is nothing to say."""
    if br is None or br.empty:
        return ""
    lines = ["## 💥 Blast radius", ""]
    eps = br.endpoints
    icon = RISK_ICON[br.risk]
    risk = f"{icon} **{br.risk.capitalize()} risk**"
    if eps:
        names = ", ".join(_code(a.entry.name) for a in eps[:8])
        more = f" and {len(eps) - 8} more" if len(eps) > 8 else ""
        n = len(eps)
        lines.append(
            f"{risk} — this change affects **{n} endpoint{'' if n == 1 else 's'}**: {names}{more}"
        )
    elif br.affected:
        lines.append(f"{risk} — this change affects no HTTP endpoint.")
    else:
        lines.append(f"{risk} — no entry point reaches the changed code.")
    others: dict[str, int] = defaultdict(int)
    for a in br.affected:
        if a.entry.kind != "http":
            others[a.entry.kind] += 1
    if others:
        lines.append("")
        lines.append(
            "Also reaches: " + ", ".join(_count_phrase(n, k) for k, n in sorted(others.items()))
        )
    if br.sensitive:
        lines.append("")
        lines.append(
            "Sensitive operations in the changed code: "
            + "; ".join(
                f"**{cat}** ({', '.join(_code(x, 50) for x in ex)})" if ex else f"**{cat}**"
                for cat, ex in br.sensitive.items()
            )
        )
    if br.affected:
        rows = br.affected[:MAX_LISTED]
        lines += [
            "",
            "<details>",
            f"<summary>Affected entry points ({len(br.affected)})</summary>",
            "",
            "| Entry point | Kind | Auth | Location | Call path to the change |",
            "|---|---|---|---|---|",
        ]
        for a in rows:
            ep = a.entry
            auth = (
                "🔒 " + _code(ep.auth_evidence or "yes", 40)
                if ep.auth
                else ("⚠️ none detected" if ep.kind == "http" else "—")
            )
            path = " → ".join(_code(x, 40) for x in a.chain[:6]) or "—"
            lines.append(f"| {_code(ep.name)} | {_label(ep)} | {auth} | {_where(ep)} | {path} |")
        if len(br.affected) > len(rows):
            lines.append(f"\n_…and {len(br.affected) - len(rows)} more._")
        lines += ["", "</details>"]
    if br.partial:
        lines += [
            "",
            "_Partial analysis: the code graph covers only part of this repository, so more "
            "entry points may be affected._",
        ]
    lines.append("")
    if br.surface_changes:
        lines += ["### 🛡️ Attack surface changes", ""]
        for c in br.surface_changes:
            what = KIND_LABEL.get(c.kind, c.kind)
            where = _code(f"{c.path}:{c.line}", 120)
            if c.change == "added":
                note = "" if c.auth or c.kind != "http" else " — no auth check detected"
                lines.append(f"- ➕ New {what} {_code(c.name)} ({where}){note}")  # noqa: RUF001
            elif c.change == "removed":
                lines.append(f"- ➖ Removed {what} {_code(c.name)} ({where})")  # noqa: RUF001
            elif c.change == "auth_removed":
                lines.append(f"- ⚠️ {_code(c.name)} ({where}) no longer has an auth check")
            else:
                lines.append(f"- 🔒 {_code(c.name)} ({where}) now has an auth check")
        lines.append("")
    return "\n".join(lines)


def render_prompt(br: BlastRadius | None, task_files: Sequence[str] = ()) -> str:
    """A compact, untrusted-wrapped block for an agent's context pack (``""`` when empty)."""
    if br is None or br.empty:
        return ""
    wanted = set(task_files)
    rel = [a for a in br.affected if not wanted or a.changed_path in wanted] or br.affected
    out = [f"Blast radius (static reverse call-graph analysis, best effort): risk {br.risk}."]
    if rel:
        out.append(f"The changed code is reachable from {len(rel)} entry point(s):")
        for a in rel[:15]:
            ep = a.entry
            auth = f"auth: {ep.auth_evidence or 'yes'}" if ep.auth else "no auth check detected"
            out.append(
                f"- {ep.name} [{ep.framework} {ep.kind}, {auth}] {ep.path}:{ep.line} via "
                + " -> ".join(a.chain[:6])
            )
    if br.sensitive:
        out.append(
            "Sensitive operations in changed code: "
            + "; ".join(f"{k}: {', '.join(v)}" for k, v in br.sensitive.items())
        )
    for c in br.surface_changes[:10]:
        out.append(f"Attack surface: {c.change} {c.kind} {c.name} ({c.path}:{c.line})")
    body = "\n".join(out)
    return (
        untrusted("blast-radius", body)
        + "\nPrioritize problems an external caller of these entry points could trigger "
        "(injection, missing authorization, data exposure, unsafe input handling)."
    )
