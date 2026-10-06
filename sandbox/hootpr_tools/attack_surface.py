#!/usr/bin/env python3
"""HootPR attack surface map (spec §10.3, phase 6). Runs INSIDE the sealed sandbox.

Inventories a repository checkout and prints one JSON document on stdout:

- ``entry_points``: HTTP routes, CLI mains, message handlers, server actions (with auth evidence),
  from the same tree-sitter detector as the code graph (``entrypoints.py``);
- ``outbound``: calls leaving the process (HTTP clients, sockets, SMTP, cloud SDKs);
- ``sinks``: counts of auth / crypto / exec / file / db calls per category (+ a few examples);
- ``secrets``: secret-looking environment variables read by the code and committed env files
  (names and locations only: values are never read into the output);
- ``iac``: exposure in Terraform, Kubernetes, docker-compose, Dockerfiles and GitHub workflows.

Bounded for a small VM: at most --max-files source files (entry-point-looking files first).
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_graph

VERSION = 1
MAX_ENTRY_POINTS = 2000
MAX_OUTBOUND = 500
MAX_SECRETS = 300
MAX_IAC = 300
MAX_TEXT_BYTES = 256_000
PRIORITY = re.compile(
    r"(?i)(route|api|view|url|controller|handler|server|app|main|endpoint|resource|worker|"
    r"consumer|task|cli|command|auth|middleware|page|action)"
)
SECRETISH = re.compile(
    r"(?i)(secret|token|passw|api_?key|private|credential|dsn|database_url|access_key|auth|salt|"
    r"signing|webhook|client_id|session_key|encryption)"
)
ENV_READS = (
    re.compile(r"""os\.environ(?:\.get)?\s*[\[(]\s*["'](\w+)["']"""),
    re.compile(r"""os\.getenv\(\s*["'](\w+)["']"""),
    re.compile(r"""process\.env\.([A-Za-z_]\w*)"""),
    re.compile(r"""process\.env\[\s*["'](\w+)["']"""),
    re.compile(r"""os\.(?:Getenv|LookupEnv)\(\s*"(\w+)\""""),
    re.compile(r"""System\.getenv\(\s*"(\w+)\""""),
    re.compile(r"""ENV(?:\.fetch\(|\[)\s*["'](\w+)["']"""),
    re.compile(r"""getenv\(\s*["'](\w+)["']"""),
    re.compile(r"""env\(\s*["'](\w+)["']"""),
)
ENV_FILE = re.compile(r"(^|/)\.env(\.[\w-]+)?$")
ENV_FILE_OK = re.compile(r"(?i)\.(example|sample|template|dist|defaults?|test)$")
# (kind, file matcher, rule id, pattern, description)
IAC_RULES: tuple[tuple[str, re.Pattern[str], str, re.Pattern[str], str], ...] = (
    ("terraform", re.compile(r"\.tf$"), "open-cidr", re.compile(r"(0\.0\.0\.0/0|::/0)"),
     "Ingress/egress open to the whole internet"),
    ("terraform", re.compile(r"\.tf$"), "public-db", re.compile(r"publicly_accessible\s*=\s*true"),
     "Database instance is publicly accessible"),
    ("terraform", re.compile(r"\.tf$"), "public-acl", re.compile(r"acl\s*=\s*\"public-read(-write)?\""),
     "Bucket ACL grants public access"),
    ("terraform", re.compile(r"\.tf$"), "public-ip",
     re.compile(r"associate_public_ip_address\s*=\s*true"), "Instance gets a public IP"),
    ("terraform", re.compile(r"\.tf$"), "public-block-off",
     re.compile(r"(block_public_acls|block_public_policy|restrict_public_buckets)\s*=\s*false"),
     "S3 public access block disabled"),
    ("terraform", re.compile(r"\.tf$"), "unencrypted", re.compile(r"\b(encrypted|storage_encrypted)\s*=\s*false"),
     "Storage encryption disabled"),
    ("kubernetes", re.compile(r"\.ya?ml$"), "exposed-service", re.compile(r"^\s*type:\s*(LoadBalancer|NodePort)\b"),
     "Service exposed outside the cluster"),
    ("kubernetes", re.compile(r"\.ya?ml$"), "ingress", re.compile(r"^\s*kind:\s*Ingress\b"),
     "Ingress routes external traffic"),
    ("kubernetes", re.compile(r"\.ya?ml$"), "host-network", re.compile(r"^\s*hostNetwork:\s*true"),
     "Pod shares the host network"),
    ("kubernetes", re.compile(r"\.ya?ml$"), "privileged", re.compile(r"^\s*privileged:\s*true"),
     "Privileged container"),
    ("compose", re.compile(r"(^|/)(docker-)?compose[\w.-]*\.ya?ml$"), "published-port",
     re.compile(r"""^\s*-\s*["']?(\d{1,3}(\.\d{1,3}){3}:)?\d+(-\d+)?:\d+"""),
     "Port published on the host"),
    ("compose", re.compile(r"(^|/)(docker-)?compose[\w.-]*\.ya?ml$"), "host-network",
     re.compile(r"^\s*network_mode:\s*[\"']?host"), "Container uses the host network"),
    ("dockerfile", re.compile(r"(^|/)Dockerfile[\w.-]*$|\.dockerfile$"), "expose",
     re.compile(r"^\s*EXPOSE\s+\S+", re.I), "Port exposed by the image"),
    ("dockerfile", re.compile(r"(^|/)Dockerfile[\w.-]*$|\.dockerfile$"), "root-user",
     re.compile(r"^\s*USER\s+(root|0)\s*$", re.I), "Image runs as root"),
    ("github_actions", re.compile(r"^\.github/workflows/.*\.ya?ml$"), "pull-request-target",
     re.compile(r"\bpull_request_target\b"), "Workflow runs on pull_request_target (untrusted code with secrets)"),
    ("github_actions", re.compile(r"^\.github/workflows/.*\.ya?ml$"), "write-all",
     re.compile(r"permissions:\s*write-all"), "Workflow token has write-all permissions"),
)  # fmt: skip
K8S_HINT = re.compile(r"^\s*apiVersion:", re.M)


def list_files(repo: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True, timeout=60
        ).stdout.decode(errors="replace")
        return sorted(p for p in out.split("\0") if p)
    except (subprocess.SubprocessError, OSError):
        files: list[str] = []
        for root, dirs, names in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in build_graph.SKIP_DIRS]
            files += [os.path.relpath(os.path.join(root, n), repo).replace(os.sep, "/") for n in names]
        return sorted(files)


def read_text(repo: Path, path: str) -> str | None:
    try:
        p = repo / path
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_TEXT_BYTES:
            return None
        return p.read_bytes().decode(errors="replace")
    except OSError:
        return None


def _is_test(path: str) -> bool:
    return bool(re.search(r"(^|/)(tests?|__tests__|spec|e2e|fixtures?)/|[._-](test|spec)\.\w+$", path))


def scan_iac(repo: Path, files: list[str]) -> list[dict]:
    out: list[dict] = []
    for path in files:
        rules = [r for r in IAC_RULES if r[1].search(path)]
        if not rules or any(part in build_graph.SKIP_DIRS for part in path.split("/")):
            continue
        text = read_text(repo, path)
        if text is None:
            continue
        is_k8s = bool(K8S_HINT.search(text))
        for kind, _, rule, rx, desc in rules:
            if kind == "kubernetes" and not is_k8s:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    out.append({"kind": kind, "rule": rule, "path": path, "line": i, "detail": desc})
                    if len(out) >= MAX_IAC:
                        return out
    return out


def scan_secrets(repo: Path, files: list[str], sources: list[str]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for path in files:
        if ENV_FILE.search(path) and not ENV_FILE_OK.search(path):
            out.append({"name": posixpath.basename(path), "path": path, "line": 1, "source": "committed_env_file"})
    for path in sources:
        if _is_test(path):
            continue
        text = read_text(repo, path)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for rx in ENV_READS:
                for m in rx.finditer(line):
                    name = m.group(1)
                    if SECRETISH.search(name) and (name, path) not in seen:
                        seen.add((name, path))
                        out.append({"name": name, "path": path, "line": i, "source": "env"})
                        if len(out) >= MAX_SECRETS:
                            return out
    return out


def build_surface(repo: Path, max_files: int) -> dict:
    files = list_files(repo)
    sources = build_graph.list_source_files(repo)
    ranked = sorted(sources, key=lambda p: (_is_test(p), not PRIORITY.search(p), p))
    parsed = ranked[:max_files]
    entries: list[dict] = []
    outbound: list[dict] = []
    sink_counts: dict[str, int] = {}
    sink_examples: dict[str, list[dict]] = {}
    errors: list[dict] = []
    languages: dict[str, int] = {}
    for path in parsed:
        lang = build_graph._lang(path)
        languages[lang] = languages.get(lang, 0) + 1
        try:
            fg = build_graph.parse_file(repo, path, lang)
        except Exception as exc:
            errors.append({"path": path, "message": f"parse failed: {exc}"[:300]})
            continue
        names = {s["id"]: s["qualified_name"] for s in fg.symbols}
        test = _is_test(path)
        if not test:
            for e in fg.entries:
                if len(entries) < MAX_ENTRY_POINTS:
                    entries.append({**e, "handler": names.get(e["symbol"], "")})
        for x in fg.sinks:
            if test:
                continue
            cat = x["category"]
            sink_counts[cat] = sink_counts.get(cat, 0) + 1
            item = {"callee": x["callee"], "path": path, "line": x["line"],
                    "symbol": names.get(x["symbol"], "")}  # fmt: skip
            if cat == "network":
                if len(outbound) < MAX_OUTBOUND:
                    outbound.append(item)
            else:
                ex = sink_examples.setdefault(cat, [])
                if len(ex) < 20:
                    ex.append(item)
    http = [e for e in entries if e["kind"] == "http"]
    stats = {
        "source_files": len(sources),
        "parsed_files": len(parsed),
        "entry_points": len(entries),
        "http_endpoints": len(http),
        "unauthenticated_endpoints": sum(1 for e in http if not e["auth"]),
        "outbound_calls": len(outbound),
        "languages": languages,
    }
    doc = {
        "version": VERSION,
        "truncated": len(sources) > max_files or len(entries) >= MAX_ENTRY_POINTS,
        "stats": stats,
        "entry_points": entries,
        "outbound": outbound,
        "sinks": {"counts": sink_counts, "examples": sink_examples},
        "secrets": scan_secrets(repo, files, [p for p in sources if p in set(parsed)]),
        "iac": scan_iac(repo, files),
        "errors": errors[:50],
    }
    stats["secrets"] = len(doc["secrets"])
    stats["iac_findings"] = len(doc["iac"])
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HootPR attack surface map (phase 6)")
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--max-files", type=int, default=3000)
    args = ap.parse_args(argv)
    json.dump(build_surface(args.repo.resolve(), args.max_files), sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
