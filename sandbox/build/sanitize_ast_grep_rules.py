#!/usr/bin/env python3
"""Image build step: make the ast-grep-essentials pack loadable by the pinned ast-grep (plan contract C4).

Many upstream rules name local utils after the code they match (`$DB(..., password="...")`); recent ast-grep
rejects util ids with reserved characters, and one bad file makes `ast-grep scan --config` fail for the whole
pack. This renames such ids (and every `matches:` that references them) to `[A-Za-z0-9_-]` ids, copies files
that need no change byte for byte, and — with a validator binary — drops any rule the pinned ast-grep still
cannot load, so the baked pack always scans cleanly.

Usage: sanitize_ast_grep_rules.py SRC DST [AST_GREP_BIN]   (SRC/DST contain rules/ and utils/)
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

VALID_ID = re.compile(r"[A-Za-z0-9_-]+")
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def _clean(name: str) -> str:
    cleaned = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_-]+", "_", name)).strip("_-")
    return cleaned or "util"


def _rewrite_matches(node: Any, renames: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "matches" and isinstance(value, str) and value in renames:
                node[key] = renames[value]
            else:
                _rewrite_matches(value, renames)
    elif isinstance(node, list):
        for item in node:
            _rewrite_matches(item, renames)


def sanitize_doc(doc: Any) -> bool:
    """Rename invalid local util ids in one rule document, in place. Returns True when anything changed."""
    if not isinstance(doc, dict) or not isinstance(doc.get("utils"), dict):
        return False
    utils: dict[Any, Any] = doc["utils"]
    taken = {k for k in utils if isinstance(k, str) and VALID_ID.fullmatch(k)}
    renames: dict[str, str] = {}
    for key in utils:
        if isinstance(key, str) and not VALID_ID.fullmatch(key):
            base = new = _clean(key)
            n = 1
            while new in taken:
                n += 1
                new = f"{base}_{n}"
            taken.add(new)
            renames[key] = new
    if not renames:
        return False
    doc["utils"] = {renames.get(k, k): v for k, v in utils.items()}
    _rewrite_matches(doc, renames)
    return True


def _valid(validator: str, rule: Path, utils: Path) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        rules_dir = Path(tmp) / "rules"
        empty = Path(tmp) / "empty"
        rules_dir.mkdir()
        empty.mkdir()
        shutil.copy(rule, rules_dir / rule.name)
        sgconfig = Path(tmp) / "sgconfig.yml"
        sgconfig.write_text(f"ruleDirs:\n- {rules_dir}\nutilDirs:\n- {utils}\n", encoding="utf-8")
        r = subprocess.run(
            [validator, "scan", "--config", str(sgconfig), str(empty)], capture_output=True, text=True, check=False
        )
        if r.returncode != 0:
            print(f"dropping {rule}: {r.stderr.strip().splitlines()[-1:] or r.returncode}", file=sys.stderr)
        return r.returncode == 0


def sanitize(src: Path, dst: Path, validator: str | None = None) -> dict[str, int]:
    """Copy SRC/{rules,utils} to DST, fixing util ids; returns counts of kept, rewritten and dropped rules."""
    stats = {"rules": 0, "rewritten": 0, "dropped": 0}
    shutil.copytree(src / "utils", dst / "utils", dirs_exist_ok=True)
    for path in sorted((src / "rules").rglob("*.yml")):
        out = dst / "rules" / path.relative_to(src / "rules")
        out.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8")
        docs = list(yaml.load_all(text, Loader=_LOADER))
        changed = [sanitize_doc(d) for d in docs]
        if any(changed):
            out.write_text(
                yaml.dump_all(docs, Dumper=_DUMPER, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8"
            )
            stats["rewritten"] += 1
        else:
            out.write_text(text, encoding="utf-8")
        if validator is not None and not _valid(validator, out, dst / "utils"):
            out.unlink()
            stats["dropped"] += 1
            continue
        stats["rules"] += 1
    return stats


def main(argv: list[str]) -> int:
    stats = sanitize(Path(argv[0]), Path(argv[1]), argv[2] if len(argv) > 2 else None)
    print(f"ast-grep-essentials: {stats['rules']} rules ({stats['rewritten']} util ids fixed, "
          f"{stats['dropped']} dropped)")  # fmt: skip
    return 0 if stats["rules"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
