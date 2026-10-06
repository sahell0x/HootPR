#!/usr/bin/env python3
"""Image build step: merge the downloaded semgrep registry packs into one rule file, one copy per rule id.

Packs overlap heavily (p/default contains most of p/python, ...); running duplicates doubles scan time and
findings. Usage: merge_semgrep_rules.py OUT.yml PACK.yml [PACK.yml ...]
"""

import sys

import yaml


def main(out: str, packs: list[str]) -> int:
    seen: dict[str, dict] = {}
    for pack in packs:
        with open(pack, encoding="utf-8") as fh:
            doc = yaml.load(fh, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))  # noqa: S506 - safe loader
        for rule in (doc or {}).get("rules") or []:
            if isinstance(rule, dict) and rule.get("id") and rule["id"] not in seen:
                seen[rule["id"]] = rule
    if not seen:
        print("no semgrep rules downloaded", file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8") as fh:
        yaml.dump({"rules": list(seen.values())}, fh, Dumper=getattr(yaml, "CSafeDumper", yaml.SafeDumper))
    print(f"merged {len(seen)} semgrep rules from {len(packs)} packs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
