#!/usr/bin/env python3
"""HootPR code graph builder (spec §7.2, plan contract C1).

Runs INSIDE the sealed sandbox (stdlib + tree_sitter_language_pack). Parses the changed files, the
files they import and the files importing them (or the whole repo when it has <= --max-files source
files) and prints one JSON document on stdout. A bad file never fails the run: it goes to "errors".
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entrypoints  # sibling module: entry points + sinks (phase 6)

VERSION = 1
MAX_SINKS_PER_FILE = 400
MAX_FILE_BYTES = 512_000
SIG_MAX = 160
MAX_CALL_TARGETS = 5
MAX_IMPORTERS = 300
SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    "target",
    ".mypy_cache",
    ".tox",
}
EXT_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".sh": "bash",
    ".bash": "bash",
}
JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_JS_DEFS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "method_definition": "method",
    "class_declaration": "class",
    "variable_declarator": "variable",
}
_TS_DEFS = {
    **_JS_DEFS,
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}
DEFS: dict[str, dict[str, str]] = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "javascript": _JS_DEFS,
    "typescript": _TS_DEFS,
    "tsx": _TS_DEFS,
    "go": {"function_declaration": "function", "method_declaration": "method", "type_spec": "type"},
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "method_declaration": "method",
        "constructor_declaration": "method",
    },
    "ruby": {"method": "method", "singleton_method": "method", "class": "class", "module": "module"},
    "php": {
        "function_definition": "function",
        "method_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "trait_declaration": "class",
    },
    "rust": {"function_item": "function", "struct_item": "struct", "enum_item": "enum", "trait_item": "interface"},
    "c": {"function_definition": "function", "struct_specifier": "struct"},
    "cpp": {"function_definition": "function", "struct_specifier": "struct", "class_specifier": "class"},
    "csharp": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "method_declaration": "method",
        "constructor_declaration": "method",
    },
    "kotlin": {"function_declaration": "function", "class_declaration": "class", "object_declaration": "class"},
    "swift": {"function_declaration": "function", "class_declaration": "class", "protocol_declaration": "interface"},
    "bash": {"function_definition": "function"},
}
# call node type -> field naming the callee (None: first named child)
_JS_CALLS: dict[str, str | None] = {"call_expression": "function", "new_expression": "constructor"}
CALLS: dict[str, dict[str, str | None]] = {
    "python": {"call": "function"},
    "javascript": _JS_CALLS,
    "typescript": _JS_CALLS,
    "tsx": _JS_CALLS,
    "go": {"call_expression": "function"},
    "java": {"method_invocation": "name", "object_creation_expression": "type"},
    "ruby": {"call": "method", "identifier": None},
    "php": {
        "function_call_expression": "function",
        "member_call_expression": "name",
        "object_creation_expression": None,
    },
    "rust": {"call_expression": "function", "macro_invocation": "macro"},
    "c": {"call_expression": "function"},
    "cpp": {"call_expression": "function"},
    "csharp": {"invocation_expression": "function", "object_creation_expression": "type"},
    "kotlin": {"call_expression": None},
    "swift": {"call_expression": None},
    "bash": {"command": "name"},
}
IMPORTS: dict[str, set[str]] = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "tsx": {"import_statement"},
    "go": {"import_spec"},
    "java": {"import_declaration"},
    "ruby": set(),
    "php": {"namespace_use_declaration"},
    "rust": {"use_declaration"},
    "c": {"preproc_include"},
    "cpp": {"preproc_include"},
    "csharp": {"using_directive"},
    "kotlin": {"import_header"},
    "swift": {"import_declaration"},
    "bash": set(),
}
NAME_TYPES = {
    "identifier",
    "field_identifier",
    "type_identifier",
    "property_identifier",
    "constant",
    "name",
    "simple_identifier",
    "word",
    "constant_identifier",
}
STRING_TYPES = {
    "string",
    "string_literal",
    "interpreted_string_literal",
    "raw_string_literal",
    "string_fragment",
    "system_lib_string",
    "string_content",
}
HERITAGE = {
    "superclasses",
    "class_heritage",
    "superclass",
    "super_interfaces",
    "extends_clause",
    "implements_clause",
    "base_list",
    "base_class_clause",
    "delegation_specifier",
    "inheritance_specifier",
    "argument_list",
}
FN_VALUE_TYPES = {"arrow_function", "function_expression", "function", "generator_function"}
IDENT = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass
class FileGraph:
    path: str
    lang: str
    size: int
    symbols: list[dict] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)  # (scope symbol id, callee name)
    imports: list[str] = field(default_factory=list)  # raw import targets
    bases: list[tuple[str, str]] = field(default_factory=list)  # (class id, base name)
    entries: list[dict] = field(default_factory=list)  # entry points (phase 6)
    sinks: list[dict] = field(default_factory=list)  # sensitive calls (phase 6)
    error: str | None = None


def _text(node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode(errors="replace")


def _last_ident(text: str) -> str:
    found = IDENT.findall(text)
    return found[-1] if found else ""


def _name(node, src: bytes, depth: int = 0) -> str:
    n = node.child_by_field_name("name")
    if n is not None:
        return _last_ident(_text(n, src))
    d = node.child_by_field_name("declarator")
    if d is not None and depth < 4:
        return _name(d, src, depth + 1) or (_text(d, src) if d.type in NAME_TYPES else "")
    queue = list(node.named_children)
    while queue and depth < 3:
        nxt = []
        for c in queue:
            if c.type in NAME_TYPES:
                return _text(c, src)
            nxt += c.named_children
        queue, depth = nxt, depth + 1
    return ""


def _string_in(node, src: bytes, depth: int = 0) -> str | None:
    if node.type in STRING_TYPES:
        return _text(node, src).strip("'\"`<>")
    if depth > 4:
        return None
    for c in node.named_children:
        s = _string_in(c, src, depth + 1)
        if s:
            return s
    return None


def _import_target(lang: str, node, src: bytes) -> str | None:
    s = _string_in(node, src)
    if s:
        return s
    if lang == "python" and node.type == "import_from_statement":
        m = node.child_by_field_name("module_name")
        return _text(m, src) if m is not None else None
    txt = re.sub(r"^\s*(import|from|use|using|package)\b", "", _text(node, src)).strip()
    txt = re.sub(r"^static\s+", "", txt)
    tok = re.split(r"[\s;{(,]", txt, maxsplit=1)[0]
    return tok or None


def _signature(node, src: bytes) -> str:
    first = _text(node, src).splitlines()[0] if node.end_byte > node.start_byte else ""
    return first.split("{")[0].strip()[:SIG_MAX]


_CONFIGURED = False


def _tslp():  # type: ignore[no-untyped-def]
    """Import tree_sitter_language_pack lazily (CLI --help works without it) and point its grammar cache at
    HOOTPR_GRAMMAR_CACHE when set (the sandbox bakes grammars there; its root filesystem is read-only)."""
    global _CONFIGURED
    import tree_sitter_language_pack as tslp

    cache = os.environ.get("HOOTPR_GRAMMAR_CACHE")
    if cache and not _CONFIGURED and hasattr(tslp, "configure") and hasattr(tslp, "PackConfig"):
        tslp.configure(tslp.PackConfig(cache_dir=cache))
    _CONFIGURED = True
    return tslp


def parse_file(repo: Path, path: str, lang: str) -> FileGraph:
    get_parser = _tslp().get_parser

    raw = (repo / path).read_bytes()
    fg = FileGraph(path, lang, len(raw))
    tree = get_parser(lang).parse(raw)  # type: ignore[arg-type]
    module_id = f"{path}#module"
    lines = raw.count(b"\n") + 1
    fg.symbols.append(
        {
            "id": module_id,
            "kind": "module",
            "name": posixpath.splitext(posixpath.basename(path))[0],
            "qualified_name": posixpath.splitext(posixpath.basename(path))[0],
            "path": path,
            "start_line": 1,
            "end_line": lines,
            "signature": "",
        }
    )
    if tree.root_node.has_error:
        fg.error = "syntax errors (partial parse)"
    defs, calls, imports = DEFS.get(lang, {}), CALLS.get(lang, {}), IMPORTS.get(lang, set())
    det = entrypoints.Detector(lang, path, raw)
    stack = [(tree.root_node, module_id, "", False)]
    while stack:
        node, scope_id, qual, in_class = stack.pop()
        t = node.type
        child_scope, child_qual, child_in_class = scope_id, qual, in_class
        syn = det.synthetic(node)
        if syn is not None:  # a handler registered by a call: synthetic "entry" symbol scoping it
            start = node.start_point[0] + 1
            sid = f"{path}#{syn.name}@{start}"
            fg.symbols.append(
                {
                    "id": sid,
                    "kind": "entry",
                    "name": syn.name,
                    "qualified_name": syn.name,
                    "path": path,
                    "start_line": start,
                    "end_line": node.end_point[0] + 1,
                    "signature": _signature(node, raw),
                }
            )
            fg.calls += [(sid, ref) for ref in syn.handler_refs]
            fg.entries.append({**syn.entry, "symbol": sid, "path": path, "line": start})
            child_scope = sid
        kind = defs.get(t)
        if t == "variable_declarator":
            value = node.child_by_field_name("value")
            kind = "function" if value is not None and value.type in FN_VALUE_TYPES else None
        if lang == "rust" and t == "impl_item":
            ty = node.child_by_field_name("type")
            child_qual, child_in_class = (_last_ident(_text(ty, raw)) if ty is not None else qual), True
        if kind:
            name = _name(node, raw)
            if name:
                if t == "type_spec":
                    ty = node.child_by_field_name("type")
                    kind = {"struct_type": "struct", "interface_type": "interface"}.get(ty.type if ty else "", "type")
                if kind == "function" and in_class:
                    kind = "method"
                q = f"{qual}.{name}" if qual else name
                start = node.start_point[0] + 1
                sid = f"{path}#{q}@{start}"
                fg.symbols.append(
                    {
                        "id": sid,
                        "kind": kind,
                        "name": name,
                        "qualified_name": q,
                        "path": path,
                        "start_line": start,
                        "end_line": node.end_point[0] + 1,
                        "signature": _signature(node, raw),
                    }
                )
                child_scope, child_qual = sid, q
                child_in_class = kind in ("class", "interface", "struct", "module")
                ep = det.for_definition(node, name, kind)
                if ep is not None:
                    fg.entries.append({**ep, "symbol": sid, "path": path, "line": start})
                if kind == "class":
                    for c in node.children:
                        is_base = c.type in HERITAGE or node.child_by_field_name("superclasses") == c
                        if is_base:
                            for ident in IDENT.findall(_text(c, raw)):
                                if ident not in ("extends", "implements", "public", "private", "protected"):
                                    fg.bases.append((sid, ident))
        if t in calls and not (lang == "ruby" and t == "identifier"):
            fld = calls[t]
            target = node.child_by_field_name(fld) if fld else (node.named_children[0] if node.named_children else None)
            callee = _last_ident(_text(target, raw)) if target is not None else ""
            if callee:
                fg.calls.append((scope_id, callee))
                cat = entrypoints.sink_category(_text(target, raw)) if target is not None else None
                if cat and len(fg.sinks) < MAX_SINKS_PER_FILE:
                    fg.sinks.append(
                        {
                            "symbol": scope_id,
                            "category": cat,
                            "callee": entrypoints.normalize_callee(_text(target, raw))[:80],
                            "path": path,
                            "line": node.start_point[0] + 1,
                        }
                    )
        if lang == "ruby" and t == "call":
            m = node.child_by_field_name("method")
            if m is not None and _text(m, raw) in ("require", "require_relative"):
                s = _string_in(node, raw)
                if s:
                    fg.imports.append(("./" + s) if _text(m, raw) == "require_relative" else s)
        if t in imports:
            target = _import_target(lang, node, raw)
            if target:
                fg.imports.append(target)
        for c in reversed(node.children):
            stack.append((c, child_scope, child_qual, child_in_class))
    return fg


class FileIndex:
    def __init__(self, files: list[str]) -> None:
        self.files = set(files)
        self.by_name: dict[str, list[str]] = {}
        self.by_dir: dict[str, list[str]] = {}
        for p in files:
            self.by_name.setdefault(posixpath.basename(p), []).append(p)
            self.by_dir.setdefault(posixpath.dirname(p), []).append(p)

    def suffix(self, cand: str) -> list[str]:
        return [p for p in self.by_name.get(posixpath.basename(cand), []) if p == cand or p.endswith("/" + cand)]


def resolve(lang: str, raw: str, from_path: str, idx: FileIndex) -> list[str]:
    raw = raw.strip()
    here = posixpath.dirname(from_path)
    cands: list[str] = []
    if lang == "python":
        dots = len(raw) - len(raw.lstrip("."))
        rest = raw.lstrip(".").replace(".", "/")
        if dots:
            d = here
            for _ in range(dots - 1):
                d = posixpath.dirname(d)
            stem = posixpath.join(d, rest) if rest else d
        else:
            stem = rest
        cands = [stem + ".py", stem + "/__init__.py"]
    elif lang in ("javascript", "typescript", "tsx") or raw.startswith("./") or raw.startswith("../"):
        if not raw.startswith("."):
            return []  # package import (node_modules): not in the repo graph
        stem = posixpath.normpath(posixpath.join(here, raw))
        exts = JS_EXTS if lang in ("javascript", "typescript", "tsx") else (".rb", "")
        cands = [stem, *(stem + e for e in exts), *(stem + "/index" + e for e in JS_EXTS)]
    elif lang == "go":
        parts = raw.split("/")
        out: list[str] = []
        for k in (2, 1):
            suffix = "/".join(parts[-k:])
            for d, files in idx.by_dir.items():
                if d == suffix or d.endswith("/" + suffix):
                    out += [f for f in files if f.endswith(".go")]
            if out:
                return sorted(set(out))[:10]
        return []
    elif lang in ("c", "cpp"):
        cands = [posixpath.normpath(posixpath.join(here, raw)), raw]
    else:
        stem = re.sub(r"(::|\\|\.)", "/", raw).removeprefix("crate/").rstrip("/*;")
        exts = {
            "java": ".java",
            "kotlin": ".kt",
            "csharp": ".cs",
            "php": ".php",
            "rust": ".rs",
            "ruby": ".rb",
            "swift": ".swift",
        }.get(lang, "")
        cands = [stem + exts, stem.rsplit("/", 1)[0] + exts] if exts else [stem]
    exact = [c for c in cands if c in idx.files]
    if exact:
        return exact[:5]
    found: list[str] = []
    for c in cands:
        found += idx.suffix(c)
    return sorted(set(found))[:5]


def list_source_files(repo: Path) -> list[str]:
    try:
        out = (
            subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True, timeout=60)
            .stdout.decode(errors="replace")
            .split("\0")
        )
        files = [p for p in out if p]
    except (subprocess.SubprocessError, OSError):
        files = []
        for root, dirs, names in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for n in names:
                files.append(os.path.relpath(os.path.join(root, n), repo).replace(os.sep, "/"))
    keep = []
    for p in files:
        if any(part in SKIP_DIRS for part in p.split("/")[:-1]):
            continue
        if posixpath.splitext(p)[1].lower() not in EXT_LANG:
            continue
        try:
            if (repo / p).stat().st_size <= MAX_FILE_BYTES:
                keep.append(p)
        except OSError:
            continue
    return sorted(keep)


def _importers(repo: Path, changed: list[str], all_src: set[str]) -> list[str]:
    out: list[str] = []
    for p in changed:
        stem = posixpath.splitext(posixpath.basename(p))[0]
        if len(stem) < 3 or stem in ("index", "main", "__init__", "mod", "lib"):
            stem = posixpath.basename(posixpath.dirname(p)) or stem
        if len(stem) < 3:
            continue
        try:
            r = subprocess.run(
                ["git", "-C", str(repo), "grep", "-l", "-I", "-F", "-e", stem], capture_output=True, timeout=60
            )
        except (subprocess.SubprocessError, OSError):
            continue
        out += [q for q in r.stdout.decode(errors="replace").splitlines() if q in all_src]
        if len(out) >= MAX_IMPORTERS:
            break
    return out[:MAX_IMPORTERS]


def _lang(path: str) -> str:
    return EXT_LANG[posixpath.splitext(path)[1].lower()]


def build(repo: Path, changed: list[str], max_files: int, max_symbols: int, external_calls: bool = False) -> dict:
    all_src = list_source_files(repo)
    src_set = set(all_src)
    for p in changed:  # changed files may be untracked in tests / local runs
        if p not in src_set and (repo / p).is_file() and posixpath.splitext(p)[1].lower() in EXT_LANG:
            all_src.append(p)
            src_set.add(p)
    idx = FileIndex(all_src)
    changed_src = [p for p in changed if p in src_set]
    graphs: dict[str, FileGraph] = {}
    errors: list[dict] = []

    def parse(p: str) -> None:
        if p in graphs:
            return
        try:
            graphs[p] = parse_file(repo, p, _lang(p))
            if graphs[p].error:
                errors.append({"path": p, "message": graphs[p].error})
        except Exception as exc:
            errors.append({"path": p, "message": f"parse failed: {exc}"[:300]})

    if len(all_src) <= max_files:
        scope, targets = "full", [*changed_src, *[p for p in all_src if p not in set(changed_src)]]
        for p in targets:
            parse(p)
    else:
        scope = "changed+1hop"
        for p in changed_src:
            parse(p)
        extra: list[str] = []
        for p in changed_src:
            if p in graphs:
                for raw in graphs[p].imports:
                    extra += resolve(graphs[p].lang, raw, p, idx)
        extra += _importers(repo, changed_src, src_set)
        for p in extra:
            parse(p)
    order = [*changed_src, *[p for p in graphs if p not in set(changed_src)]]
    symbols: list[dict] = []
    truncated = False
    kept_files: list[dict] = []
    for p in order:
        fg = graphs.get(p)
        if fg is None:
            continue
        room = max_symbols - len(symbols)
        if room <= 0:
            truncated = True
            break
        take = fg.symbols[:room]
        truncated = truncated or len(take) < len(fg.symbols)
        symbols += take
        kept_files.append({"path": p, "language": fg.lang, "size": fg.size, "symbols": [s["id"] for s in take]})
    known = {s["id"] for s in symbols}
    by_name: dict[str, list[str]] = {}
    for s in symbols:
        if s["kind"] != "module":
            by_name.setdefault(s["name"], []).append(s["id"])
    edges: set[tuple[str, str, str]] = set()
    external: set[tuple[str, str]] = set()  # (caller id, callee name) not defined in this repo
    cap = max_symbols * 3
    for p in order:
        fg = graphs.get(p)
        if fg is None:
            continue
        for scope_id, callee in fg.calls:
            if scope_id in known:
                if external_calls and callee not in by_name and len(external) < cap:
                    external.add((scope_id, callee))
                for t in by_name.get(callee, [])[:MAX_CALL_TARGETS]:
                    if t != scope_id:
                        edges.add((scope_id, t, "calls"))
        for raw in fg.imports:
            for target in resolve(fg.lang, raw, p, idx):
                src_id, dst_id = f"{p}#module", f"{target}#module"
                if src_id in known and dst_id in known and src_id != dst_id:
                    edges.add((src_id, dst_id, "imports"))
        for cls_id, base in fg.bases:
            for t in by_name.get(base, [])[:MAX_CALL_TARGETS]:
                if cls_id in known and t != cls_id:
                    edges.add((cls_id, t, "inherits"))
        if len(edges) >= cap:
            truncated = True
            break
    doc = {
        "version": VERSION,
        "scope": scope,
        "truncated": truncated,
        "files": kept_files,
        "symbols": symbols,
        "edges": [{"from": a, "to": b, "kind": k} for a, b, k in sorted(edges)][:cap],
        "errors": errors,
    }
    # phase 6: entry points + sensitive sinks (security suite)
    doc["entry_points"] = [e for p in order if p in graphs for e in graphs[p].entries if e["symbol"] in known]
    doc["sinks"] = [x for p in order if p in graphs for x in graphs[p].sinks if x["symbol"] in known][:max_symbols]
    if external_calls:  # phase 7: linked repositories (cross-repo callers)
        doc["external_calls"] = [{"from": a, "name": n} for a, n in sorted(external)]
    return doc


def _download(langs: list[str]) -> None:
    """Fetch grammars ahead of time (image build): the analysis sandbox is sealed, so tree-sitter-language-pack
    (>= 1.0 downloads parsers lazily) must find them in its cache: HOOTPR_GRAMMAR_CACHE, else XDG_CACHE_HOME."""
    tslp = _tslp()
    for lang in langs:  # get_parser fetches into the configured cache (download() may use another dir)
        tslp.get_parser(lang)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HootPR code graph (contract C1)")
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--changed", action="append", default=[])
    ap.add_argument("--max-files", type=int, default=3000)
    ap.add_argument("--max-symbols", type=int, default=20000)
    ap.add_argument("--external-calls", action="store_true", help="also list calls to names not defined in this repo")
    ap.add_argument("--prefetch", action="store_true", help="download every grammar used here, then exit")
    args = ap.parse_args(argv)  # exits 2 on bad arguments
    if args.prefetch:
        langs = sorted(set(EXT_LANG.values()))
        _download(langs)
        json.dump({"version": VERSION, "prefetched": langs}, sys.stdout)
        return 0
    if args.repo is None:
        ap.error("--repo is required")  # exits 2
    doc = build(
        args.repo.resolve(),
        [c.removeprefix("./") for c in args.changed],
        args.max_files,
        args.max_symbols,
        args.external_calls,
    )
    json.dump(doc, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
