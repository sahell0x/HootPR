"""Cross-repo breaking API changes (spec §10.4).

A public definition whose line is removed from the diff (and not re-added) or whose signature
line changes is an API change; when a linked repository still calls that name, HootPR raises a
``major`` bug candidate. The candidate goes through the judge like every other finding.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.kb.linked import LinkedGraph
from app.platforms.base import FileDiff, Hunk
from app.review.findings import Candidate
from app.review.graph import CodeGraph

ChangeKind = Literal["removed", "signature_changed"]
MIN_NAME_LEN = 4
MAX_CALLERS_LISTED = 5
MAX_FINDINGS = 10
# Names too generic to match across repositories by name alone.
GENERIC = frozenset(
    {
        "main", "init", "__init__", "run", "get", "set", "call", "handle", "handler", "test",
        "setup", "teardown", "close", "open", "read", "write", "load", "save", "update",
        "create", "delete", "render", "start", "stop", "execute", "process", "apply", "build",
        "parse", "format", "validate", "toString", "equals", "hashCode", "constructor",
    }
)  # fmt: skip

_DEF_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "py": [
        re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<sig>.*)"),
        re.compile(r"^\s*class\s+(?P<name>[A-Za-z_]\w*)(?P<sig>.*)"),
    ],
    "js": [
        re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
            r"(?P<name>[A-Za-z_$][\w$]*)\s*(?P<sig>[(<].*)"
        ),
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
            r"(?::[^=]+)?=\s*(?P<sig>(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>.*)"
        ),
        re.compile(
            r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)(?P<sig>.*)"
        ),
    ],
    "go": [re.compile(r"^func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_]\w*)\s*(?P<sig>[\[(].*)")],
    "rb": [re.compile(r"^\s*def\s+(?:self\.)?(?P<name>[A-Za-z_]\w*[?!]?)(?P<sig>.*)")],
    "rs": [
        re.compile(r"^\s*pub(?:\([^)]*\))?\s+(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)(?P<sig>.*)")
    ],
    "java": [
        re.compile(
            r"^\s*public\s+(?:static\s+|final\s+|abstract\s+|synchronized\s+)*"
            r"[\w<>\[\],.? ]+\s+(?P<name>[A-Za-z_]\w*)\s*(?P<sig>\(.*)"
        )
    ],
    "kt": [
        re.compile(
            r"^\s*(?:public\s+|open\s+|override\s+|suspend\s+)*fun\s+(?:<[^>]*>\s*)?"
            r"(?:[\w.]+\.)?(?P<name>[A-Za-z_]\w*)\s*(?P<sig>\(.*)"
        )
    ],
}  # fmt: skip
_EXT = {
    ".py": "py", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js",
    ".tsx": "js", ".go": "go", ".rb": "rb", ".rs": "rs", ".java": "java", ".kt": "kt",
}  # fmt: skip


@dataclass(frozen=True)
class ApiChange:
    path: str
    name: str
    kind: ChangeKind
    old: str  # removed definition line
    new: str | None  # replacement definition line
    anchor: int | None  # new-side line to comment on


def _lang(path: str) -> str | None:
    dot = path.rfind(".")
    return _EXT.get(path[dot:].lower()) if dot >= 0 else None


def _is_public(lang: str, name: str) -> bool:
    if len(name) < MIN_NAME_LEN or name in GENERIC:
        return False
    if lang == "go":
        return name[:1].isupper()
    return not name.startswith("_")


def _match(lang: str, text: str) -> tuple[str, str] | None:
    for pat in _DEF_PATTERNS.get(lang, []):
        m = pat.match(text)
        if m:
            return m.group("name"), m.group("sig")
    return None


def _norm(sig: str) -> str:
    sig = re.sub(r"\s+", "", sig)
    return sig.rstrip(":{;")


def _anchor_near(h: Hunk, idx: int) -> int | None:
    """The new-side line closest after (else before) position ``idx`` inside the hunk."""
    for ln in h.lines[idx:]:
        if ln.new_line is not None:
            return ln.new_line
    for ln in reversed(h.lines[:idx]):
        if ln.new_line is not None:
            return ln.new_line
    return None


def api_changes(files: Iterable[FileDiff], graph: CodeGraph | None = None) -> list[ApiChange]:
    """Public definitions removed or re-signed by the diff."""
    out: list[ApiChange] = []
    for f in files:
        lang = _lang(f.path)
        if lang is None or f.is_binary:
            continue
        removed: dict[str, tuple[str, str, int | None]] = {}
        added: dict[str, tuple[str, str, int | None]] = {}
        for h in f.hunks:
            for i, ln in enumerate(h.lines):
                if ln.kind not in ("add", "del"):
                    continue
                hit = _match(lang, ln.text)
                if hit is None or not _is_public(lang, hit[0]):
                    continue
                name, sig = hit
                if ln.kind == "del":
                    removed.setdefault(name, (ln.text.strip(), sig, _anchor_near(h, i)))
                else:
                    added.setdefault(name, (ln.text.strip(), sig, ln.new_line))
        for name, (old_text, old_sig, anchor) in removed.items():
            if name in added:
                new_text, new_sig, new_line = added[name]
                if _norm(new_sig) != _norm(old_sig):
                    out.append(
                        ApiChange(f.path, name, "signature_changed", old_text, new_text, new_line)
                    )
            elif f.status == "removed" or graph is None or not graph.find_symbol(name):
                out.append(ApiChange(f.path, name, "removed", old_text, None, anchor))
    return out


def breaking_change_findings(
    files: Iterable[FileDiff], graph: CodeGraph | None, linked: list[LinkedGraph]
) -> list[Candidate]:
    """Candidates for API changes that linked repositories still depend on."""
    if not linked:
        return []
    out: list[Candidate] = []
    for ch in api_changes(files, graph):
        if ch.anchor is None:
            continue
        users: list[str] = []
        for lg in linked:
            users += [lg.ref(s) for s in lg.callers_of(ch.name, limit=MAX_CALLERS_LISTED)]
        if not users:
            continue
        repos = sorted({u.split("]", 1)[0].lstrip("[") for u in users})
        what = (
            f"removes `{ch.name}`"
            if ch.kind == "removed"
            else f"changes the signature of `{ch.name}`"
        )
        listed = "\n".join(f"- `{u}`" for u in users[:MAX_CALLERS_LISTED])
        body = (
            f"This change {what}, but linked "
            f"{'repository' if len(repos) == 1 else 'repositories'} {', '.join(repos)} still "
            f"call it:\n\n{listed}\n\nBefore: `{ch.old[:200]}`"
            + (f"\nAfter: `{ch.new[:200]}`" if ch.new else "")
            + "\n\nKeep a backward-compatible shim or update the dependent repositories in "
            "lockstep."
        )
        out.append(
            Candidate(
                path=ch.path,
                start_line=None,
                end_line=ch.anchor,
                severity="major",
                category="bug",
                title=f"Cross-repo breaking change: `{ch.name}` is used by {', '.join(repos)}",
                body=body,
                evidence=users[:MAX_CALLERS_LISTED],
                confidence=0.75,
                source="cross_repo",
            )
        )
        if len(out) >= MAX_FINDINGS:
            break
    return out
