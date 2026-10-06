#!/usr/bin/env python3
"""HootPR static-analysis runner (spec §7.3, plan contract C1).

Runs INSIDE the sealed sandbox, stdlib only. Only tools relevant to the changed files run; every tool
uses a HootPR-owned config from --configs (never repository configs that can execute code). Output is
one JSON document on stdout; a failing tool is recorded, never fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

VERSION = 1
MAX_PER_TOOL = 500
MAX_PER_FILE = 100
STDERR_MAX = 2000
STDERR_KEEP_BYTES = 64_000
EXEC_OVERFLOW, EXEC_NOSTART = -1000, -1001  # pseudo exit codes from _exec
MAX_OUTPUT_BYTES = 64 * 1024 * 1024  # a tool's JSON above this is dropped (sandbox memory budget)
GITLEAKS_REPORT = Path(tempfile.gettempdir()) / "hootpr-gitleaks.json"
PHPSTAN_PHAR = os.environ.get("HOOTPR_PHPSTAN", "/opt/hootpr/bin/phpstan.phar")
TRIVY_CACHE = os.environ.get("HOOTPR_TRIVY_CACHE", "/opt/trivy-cache")
WORK_CACHE = Path(os.environ.get("HOOTPR_WORK_CACHE", "/work/.hootpr"))

PY = {".py", ".pyi"}
JS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
YAML = {".yml", ".yaml"}
SEMGREP_EXTS = (
    PY
    | JS
    | {
        ".go",
        ".java",
        ".rb",
        ".php",
        ".rs",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".kt",
        ".kts",
        ".swift",
        ".scala",
        ".sh",
        ".bash",
        ".tf",
        ".html",
    }
    | YAML
)
MANIFESTS = {
    "requirements.txt",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.mod",
    "go.sum",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "pom.xml",
    "build.gradle",
    "packages.lock.json",
}


@dataclass
class Ctx:
    repo: Path
    changed: list[str]
    configs: Path
    timeout: int
    base: str | None
    head: str | None
    phpstan_level: int
    semgrep_config: str | None
    # Lockfiles/manifests HootPR never reviews line by line but Trivy scans for vulnerable dependencies.
    manifests: list[str] = field(default_factory=list)
    deadline: float | None = None  # time.monotonic() by which every tool must have finished


def _ext(p: str) -> str:
    return PurePosixPath(p).suffix.lower()


def _name(p: str) -> str:
    return PurePosixPath(p).name


def is_dockerfile(p: str) -> bool:
    n = _name(p)
    return n == "Dockerfile" or n.startswith("Dockerfile.") or n.endswith(".dockerfile")


def is_workflow(p: str) -> bool:
    return p.startswith(".github/workflows/") and _ext(p) in YAML


def is_iac(p: str) -> bool:
    return _ext(p) == ".tf" or p.endswith(".tf.json") or is_dockerfile(p) or _ext(p) in YAML


def rel(ctx: Ctx, p: object) -> str:
    s = str(p)
    root = str(ctx.repo).rstrip("/") + "/"
    if s.startswith(root):
        s = s[len(root) :]
    return s.removeprefix("./").lstrip("/")


def item(tool: str, rule: object, path: str, line: object, end: object, sev: str, msg: object) -> dict:
    ln = max(1, int(line or 1))
    return {
        "tool": tool,
        "rule_id": str(rule or ""),
        "path": path,
        "line": ln,
        "end_line": max(ln, int(end or ln)),
        "severity": sev,
        "message": str(msg or "")[:500],
    }


# --- parsers ---------------------------------------------------------------------------------------
def _semgrep_rule(ctx: Ctx, check_id: object) -> str:
    """Rules loaded from a local file get its directory as an id prefix (opt.hootpr.configs.semgrep.x)."""
    rid = str(check_id or "")
    prefix = ".".join(p for p in (ctx.configs / "semgrep").parts if p != "/") + "."
    return rid.removeprefix(prefix)


def parse_semgrep(out: str, err: str, ctx: Ctx) -> list[dict]:
    sev = {"ERROR": "error", "WARNING": "warning", "INFO": "info"}
    return [
        item(
            "semgrep",
            _semgrep_rule(ctx, r.get("check_id")),
            rel(ctx, r["path"]),
            r["start"]["line"],
            r["end"]["line"],
            sev.get(str(r.get("extra", {}).get("severity")).upper(), "warning"),
            r.get("extra", {}).get("message"),
        )
        for r in json.loads(out or "{}").get("results", [])
    ]


def parse_gitleaks(out: str, err: str, ctx: Ctx) -> list[dict]:
    data = json.loads(GITLEAKS_REPORT.read_text() or "[]") if GITLEAKS_REPORT.exists() else []
    return [
        item(
            "gitleaks",
            r.get("RuleID"),
            rel(ctx, r.get("File")),
            r.get("StartLine"),
            r.get("EndLine"),
            "error",
            f"{r.get('Description') or 'Secret detected'} (value redacted)",
        )
        for r in data or []
    ]


def _trivy_sev(s: object) -> str:
    return {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning"}.get(str(s).upper(), "info")


def parse_trivy(out: str, err: str, ctx: Ctx) -> list[dict]:
    items: list[dict] = []
    for res in json.loads(out or "{}").get("Results") or []:
        target = rel(ctx, res.get("Target", ""))
        for v in res.get("Vulnerabilities") or []:
            msg = f"{v.get('PkgName')} {v.get('InstalledVersion')}: {v.get('Title') or v.get('VulnerabilityID')}"
            if v.get("FixedVersion"):
                msg += f" (fixed in {v['FixedVersion']})"
            items.append(item("trivy", v.get("VulnerabilityID"), target, 1, 1, _trivy_sev(v.get("Severity")), msg))
        for m in res.get("Misconfigurations") or []:
            cm = m.get("CauseMetadata") or {}
            items.append(
                item(
                    "trivy",
                    m.get("ID"),
                    target,
                    cm.get("StartLine"),
                    cm.get("EndLine"),
                    _trivy_sev(m.get("Severity")),
                    f"{m.get('Title')}: {m.get('Message')}",
                )
            )
        for sct in res.get("Secrets") or []:
            items.append(
                item(
                    "trivy",
                    sct.get("RuleID"),
                    target,
                    sct.get("StartLine"),
                    sct.get("EndLine"),
                    "error",
                    f"{sct.get('Title')} (value redacted)",
                )
            )
    return items


def parse_checkov(out: str, err: str, ctx: Ctx) -> list[dict]:
    data = json.loads(out or "[]")
    reports = data if isinstance(data, list) else [data]
    items = []
    for rep in reports:
        for c in (rep.get("results") or {}).get("failed_checks") or []:
            lines = c.get("file_line_range") or [1, 1]
            sev = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning"}.get(
                str(c.get("severity")).upper(), "warning"
            )
            items.append(
                item(
                    "checkov",
                    c.get("check_id"),
                    rel(ctx, c.get("file_path", "")),
                    lines[0],
                    lines[-1],
                    sev,
                    c.get("check_name"),
                )
            )
    return items


def parse_ruff(out: str, err: str, ctx: Ctx) -> list[dict]:
    def sev(code: str) -> str:
        return "error" if code.startswith("S") else "warning" if code[:1] in ("F", "B", "E") else "info"

    return [
        item(
            "ruff",
            r.get("code"),
            rel(ctx, r["filename"]),
            r["location"]["row"],
            (r.get("end_location") or {}).get("row"),
            sev(str(r.get("code") or "")),
            r.get("message"),
        )
        for r in json.loads(out or "[]")
    ]


def parse_eslint(out: str, err: str, ctx: Ctx) -> list[dict]:
    items = []
    for f in json.loads(out or "[]"):
        for m in f.get("messages", []):
            items.append(
                item(
                    "eslint",
                    m.get("ruleId") or "parse",
                    rel(ctx, f["filePath"]),
                    m.get("line"),
                    m.get("endLine"),
                    "error" if m.get("severity") == 2 else "warning",
                    m.get("message"),
                )
            )
    return items


def _level(level: object) -> str:
    return {"error": "error", "warning": "warning"}.get(str(level).lower(), "info")


def parse_shellcheck(out: str, err: str, ctx: Ctx) -> list[dict]:
    return [
        item(
            "shellcheck",
            f"SC{r.get('code')}",
            rel(ctx, r["file"]),
            r.get("line"),
            r.get("endLine"),
            _level(r.get("level")),
            r.get("message"),
        )
        for r in json.loads(out or "[]")
    ]


def parse_hadolint(out: str, err: str, ctx: Ctx) -> list[dict]:
    return [
        item(
            "hadolint",
            r.get("code"),
            rel(ctx, r["file"]),
            r.get("line"),
            r.get("line"),
            _level(r.get("level")),
            r.get("message"),
        )
        for r in json.loads(out or "[]")
    ]


def parse_actionlint(out: str, err: str, ctx: Ctx) -> list[dict]:
    return [
        item(
            "actionlint",
            r.get("kind"),
            rel(ctx, r["filepath"]),
            r.get("line"),
            r.get("line"),
            "warning",
            r.get("message"),
        )
        for r in json.loads(out or "[]")
    ]


_YAMLLINT = re.compile(r"^(?P<path>.+?):(?P<line>\d+):\d+: \[(?P<level>\w+)\] (?P<msg>.*?)(?: \((?P<rule>[\w-]+)\))?$")


def parse_yamllint(out: str, err: str, ctx: Ctx) -> list[dict]:
    items = []
    for line in out.splitlines():
        m = _YAMLLINT.match(line.strip())
        if m:
            items.append(
                item("yamllint", m["rule"], rel(ctx, m["path"]), m["line"], m["line"], _level(m["level"]), m["msg"])
            )
    return items


def parse_markdownlint(out: str, err: str, ctx: Ctx) -> list[dict]:
    raw = err.strip() or out.strip() or "[]"
    return [
        item(
            "markdownlint",
            (r.get("ruleNames") or [""])[0],
            rel(ctx, r["fileName"]),
            r.get("lineNumber"),
            r.get("lineNumber"),
            "info",
            r.get("ruleDescription"),
        )
        for r in json.loads(raw)
    ]


def parse_golangci_lint(out: str, err: str, ctx: Ctx) -> list[dict]:
    items = []
    for r in json.loads(out or "{}").get("Issues") or []:
        if r.get("FromLinter") == "typecheck":
            continue  # offline sandbox: missing modules are expected noise
        pos = r.get("Pos") or {}
        lr = r.get("LineRange") or {}
        items.append(
            item(
                "golangci_lint",
                r.get("FromLinter"),
                rel(ctx, pos.get("Filename", "")),
                pos.get("Line"),
                lr.get("To") or pos.get("Line"),
                "error" if r.get("FromLinter") == "gosec" else "warning",
                r.get("Text"),
            )
        )
    return items


def parse_rubocop(out: str, err: str, ctx: Ctx) -> list[dict]:
    sev = {"fatal": "error", "error": "error", "warning": "warning"}
    items = []
    for f in json.loads(out or "{}").get("files", []):
        for o in f.get("offenses", []):
            loc = o.get("location") or {}
            items.append(
                item(
                    "rubocop",
                    o.get("cop_name"),
                    rel(ctx, f["path"]),
                    loc.get("start_line"),
                    loc.get("last_line"),
                    sev.get(str(o.get("severity")), "info"),
                    o.get("message"),
                )
            )
    return items


def parse_phpstan(out: str, err: str, ctx: Ctx) -> list[dict]:
    items = []
    for path, data in (json.loads(out or "{}").get("files") or {}).items():
        for m in data.get("messages", []):
            items.append(
                item(
                    "phpstan",
                    m.get("identifier") or "phpstan",
                    rel(ctx, path),
                    m.get("line"),
                    m.get("line"),
                    "warning",
                    m.get("message"),
                )
            )
    return items


def parse_swiftlint(out: str, err: str, ctx: Ctx) -> list[dict]:
    return [
        item(
            "swiftlint",
            r.get("rule_id"),
            rel(ctx, r["file"]),
            r.get("line"),
            r.get("line"),
            _level(r.get("severity")),
            r.get("reason"),
        )
        for r in json.loads(out or "[]")
    ]


# --- commands --------------------------------------------------------------------------------------
def _cfg(ctx: Ctx, name: str) -> str:
    return str(ctx.configs / name)


def _safe_rel(p: str | None) -> str | None:
    if not p or p.startswith("/") or ".." in PurePosixPath(p).parts or not p.endswith((".yml", ".yaml")):
        return None
    return p


def c_semgrep(ctx: Ctx, files: list[str]) -> list[str]:
    cmd = [
        "semgrep",
        "scan",
        "--json",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        "--timeout",
        "20",
        "--max-target-bytes",
        "1000000",
        "--config",
        _cfg(ctx, "semgrep"),
    ]
    extra = _safe_rel(ctx.semgrep_config)  # repo semgrep rules are YAML data, safe to use
    if extra and (ctx.repo / extra).is_file():
        cmd += ["--config", extra]
    return [*cmd, "--", *files]


def c_gitleaks(ctx: Ctx, files: list[str]) -> list[str]:
    opts = [
        "--no-banner",
        "--redact",
        "--exit-code",
        "0",
        "--report-format",
        "json",
        "--report-path",
        str(GITLEAKS_REPORT),
        "--config",
        _cfg(ctx, "gitleaks.toml"),
    ]
    if ctx.base and ctx.head:
        return ["gitleaks", "git", *opts, "--log-opts", f"{ctx.base}..{ctx.head}", str(ctx.repo)]
    return ["gitleaks", "dir", *opts, str(ctx.repo)]


def c_gitleaks_fallback(ctx: Ctx, files: list[str]) -> list[str]:
    return c_gitleaks(replace(ctx, base=None, head=None), files)


def trivy_cache() -> str:
    """The image bakes the DB into a read-only dir; trivy opens it in place (`--cache-backend memory` keeps
    scan caches off disk). Without a baked DB (host runs) a writable cache under /work is used instead."""
    src = Path(TRIVY_CACHE)
    if (src / "db").is_dir():
        return str(src)
    dst = WORK_CACHE / "trivy-cache"
    dst.mkdir(parents=True, exist_ok=True)
    return str(dst)


def c_trivy(ctx: Ctx, files: list[str]) -> list[str]:
    return [
        "trivy",
        "fs",
        "--quiet",
        "--format",
        "json",
        "--scanners",
        "vuln,misconfig,secret",
        "--skip-db-update",
        "--skip-java-db-update",
        "--skip-check-update",
        "--offline-scan",
        "--cache-dir",
        trivy_cache(),
        "--cache-backend",
        "memory",
        "--skip-dirs",
        "node_modules",
        "--skip-dirs",
        "vendor",
        "--exit-code",
        "0",
        str(ctx.repo),
    ]


def c_checkov(ctx: Ctx, files: list[str]) -> list[str]:
    cmd = ["checkov", "--quiet", "--compact", "--output", "json", "--skip-download", "--soft-fail"]
    for f in files:
        cmd += ["-f", f]
    return cmd


def c_ruff(ctx: Ctx, files: list[str]) -> list[str]:
    return [
        "ruff",
        "check",
        "--config",
        _cfg(ctx, "ruff.toml"),
        "--output-format",
        "json",
        "--no-cache",
        "--exit-zero",
        "--",
        *files,
    ]


def c_eslint(ctx: Ctx, files: list[str]) -> list[str]:
    return [
        "eslint",
        "--config",
        _cfg(ctx, "eslint.config.mjs"),
        "--format",
        "json",
        "--no-warn-ignored",
        "--no-error-on-unmatched-pattern",
        "--",
        *files,
    ]


def c_shellcheck(ctx: Ctx, files: list[str]) -> list[str]:
    return ["shellcheck", "--norc", "-f", "json", "-S", "style", "--", *files]


def c_hadolint(ctx: Ctx, files: list[str]) -> list[str]:
    return ["hadolint", "--no-fail", "-f", "json", "--config", _cfg(ctx, "hadolint.yaml"), *files]


def c_actionlint(ctx: Ctx, files: list[str]) -> list[str]:
    return [
        "actionlint",
        "-format",
        "{{json .}}",
        "-no-color",
        "-pyflakes=",
        "-config-file",
        _cfg(ctx, "actionlint.yaml"),
        *files,
    ]


def c_yamllint(ctx: Ctx, files: list[str]) -> list[str]:
    return ["yamllint", "-f", "parsable", "-c", _cfg(ctx, "yamllint.yaml"), "--", *files]


def c_markdownlint(ctx: Ctx, files: list[str]) -> list[str]:
    return ["markdownlint", "--json", "--config", _cfg(ctx, "markdownlint.json"), "--", *files]


def c_golangci_lint(ctx: Ctx, files: list[str]) -> list[str]:
    dirs = sorted({"./" + (posixpath.dirname(f) or ".") for f in files})
    return [
        "golangci-lint",
        "run",
        "--no-config",
        "--default=none",
        "-E",
        "govet",
        "-E",
        "errcheck",
        "-E",
        "staticcheck",
        "-E",
        "ineffassign",
        "-E",
        "unused",
        "-E",
        "gosec",
        "--output.json.path=stdout",
        "--show-stats=false",
        "--issues-exit-code",
        "0",
        "--timeout",
        f"{ctx.timeout * 2}s",
        *dirs,
    ]


def c_rubocop(ctx: Ctx, files: list[str]) -> list[str]:
    return [
        "rubocop",
        "--config",
        _cfg(ctx, "rubocop.yml"),
        "--format",
        "json",
        "--force-exclusion",
        "--cache",
        "false",
        "--",
        *files,
    ]


def c_phpstan(ctx: Ctx, files: list[str]) -> list[str]:
    return [
        "php",
        "-d",
        "memory_limit=512M",
        PHPSTAN_PHAR,
        "analyse",
        "--no-progress",
        "--no-interaction",
        "--error-format=json",
        "--level",
        str(ctx.phpstan_level),
        "--configuration",
        _cfg(ctx, "phpstan.neon"),
        "--memory-limit=512M",
        "--",
        *files,
    ]


def c_swiftlint(ctx: Ctx, files: list[str]) -> list[str]:
    return ["swiftlint", "lint", "--quiet", "--reporter", "json", "--config", _cfg(ctx, "swiftlint.yml"), *files]


GO_ENV = {
    "GOFLAGS": "-mod=mod",
    "GOPROXY": "off",
    "GOTOOLCHAIN": "local",
    "CGO_ENABLED": "0",
    "GOCACHE": str(WORK_CACHE / "go-cache"),
    "GOPATH": str(WORK_CACHE / "gopath"),
    "GOLANGCI_LINT_CACHE": str(WORK_CACHE / "golangci-cache"),
}


@dataclass(frozen=True)
class Tool:
    name: str
    binary: str
    relevant: Callable[[str], bool]
    command: Callable[[Ctx, list[str]], list[str]]
    parse: Callable[[str, str, Ctx], list[dict]]
    timeout_factor: float = 1.0
    env: dict[str, str] = field(default_factory=dict)
    fallback: Callable[[Ctx, list[str]], list[str]] | None = None
    per_module: bool = False  # golangci-lint: run from each go.mod root
    # Run from an empty scratch dir (HOME too) with absolute paths: these tools auto-load repo files from
    # the cwd that can execute code (.checkov.yaml external checks, vendor/autoload.php, .rubocop args).
    isolated: bool = False

    def available(self) -> bool:
        if self.name == "phpstan":
            return shutil.which("php") is not None and Path(PHPSTAN_PHAR).is_file()
        return shutil.which(self.binary) is not None


TOOLS: list[Tool] = [
    Tool(
        "semgrep",
        "semgrep",
        lambda p: _ext(p) in SEMGREP_EXTS or is_dockerfile(p),
        c_semgrep,
        parse_semgrep,
        2.0,
        {"SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"},
    ),
    Tool("gitleaks", "gitleaks", lambda p: True, c_gitleaks, parse_gitleaks, fallback=c_gitleaks_fallback),
    Tool("trivy", "trivy", lambda p: _name(p) in MANIFESTS or is_iac(p), c_trivy, parse_trivy, 2.0),
    Tool(
        "checkov",
        "checkov",
        lambda p: (
            _ext(p) == ".tf" or p.endswith(".tf.json") or is_dockerfile(p) or (_ext(p) in YAML and not is_workflow(p))
        ),
        c_checkov,
        parse_checkov,
        2.0,
        isolated=True,
    ),
    Tool("ruff", "ruff", lambda p: _ext(p) in PY, c_ruff, parse_ruff),
    Tool("eslint", "eslint", lambda p: _ext(p) in JS, c_eslint, parse_eslint, 1.5),
    Tool("shellcheck", "shellcheck", lambda p: _ext(p) in (".sh", ".bash"), c_shellcheck, parse_shellcheck),
    Tool("hadolint", "hadolint", is_dockerfile, c_hadolint, parse_hadolint),
    Tool("actionlint", "actionlint", is_workflow, c_actionlint, parse_actionlint),
    Tool("yamllint", "yamllint", lambda p: _ext(p) in YAML, c_yamllint, parse_yamllint),
    Tool("markdownlint", "markdownlint", lambda p: _ext(p) == ".md", c_markdownlint, parse_markdownlint),
    Tool(
        "golangci_lint",
        "golangci-lint",
        lambda p: _ext(p) == ".go",
        c_golangci_lint,
        parse_golangci_lint,
        2.0,
        GO_ENV,
        per_module=True,
    ),
    Tool(
        "rubocop",
        "rubocop",
        lambda p: _ext(p) == ".rb" or _name(p) in ("Gemfile", "Rakefile"),
        c_rubocop,
        parse_rubocop,
        isolated=True,
    ),
    Tool("phpstan", "php", lambda p: _ext(p) == ".php", c_phpstan, parse_phpstan, 1.5, isolated=True),
    Tool("swiftlint", "swiftlint", lambda p: _ext(p) == ".swift", c_swiftlint, parse_swiftlint),
]


def select_files(tool: Tool, changed: list[str], manifests: list[str] | None = None) -> list[str]:
    extra = [m for m in manifests or [] if m not in changed] if tool.name == "trivy" else []
    return [p for p in [*changed, *extra] if tool.relevant(p)]


class _Capped:
    """Drains one pipe in a thread, keeping at most `cap` bytes (the rest is read and discarded)."""

    def __init__(self, stream, cap: int) -> None:  # type: ignore[no-untyped-def]
        self.buf = bytearray()
        self.overflow = False
        self._t = threading.Thread(target=self._pump, args=(stream, cap), daemon=True)
        self._t.start()

    def _pump(self, stream, cap: int) -> None:  # type: ignore[no-untyped-def]
        with stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                room = cap - len(self.buf)
                if room > 0:
                    self.buf += chunk[:room]
                if len(chunk) > room:
                    self.overflow = True

    def text(self, wait: float) -> str:
        self._t.join(wait)
        return bytes(self.buf).decode(errors="replace")


def _kill_group(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


# Environment variables that make tools load extra code or arguments; never passed through.
UNSAFE_ENV = frozenset({"RUBOCOP_OPTS", "RUBYOPT", "RUBYLIB", "PHP_INI_SCAN_DIR", "NODE_OPTIONS", "PYTHONSTARTUP"})


def _exec(argv: list[str], cwd: Path, timeout: float, env: dict[str, str]) -> tuple[int, str, str, bool]:
    """Run one tool: own process group (a timeout kills grandchildren too), output streamed and capped."""
    base = {k: v for k, v in os.environ.items() if k not in UNSAFE_ENV}
    full_env = {**base, "HOME": os.environ.get("HOME", tempfile.gettempdir()), "NO_COLOR": "1", **env}
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=full_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return EXEC_NOSTART, "", f"cannot start {argv[0]}: {exc}", False
    out, err = _Capped(proc.stdout, MAX_OUTPUT_BYTES), _Capped(proc.stderr, STDERR_KEEP_BYTES)
    timed_out = False
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        code = proc.wait()
    _kill_group(proc)  # leftovers (daemonized children) never outlive the tool
    stdout, stderr = out.text(5), err.text(5)
    if out.overflow and not timed_out:
        return EXEC_OVERFLOW, "", f"output exceeded {MAX_OUTPUT_BYTES} bytes; results dropped\n{stderr}", False
    return (124 if timed_out else code), stdout, stderr, timed_out


def _go_module_root(repo: Path, path: str) -> Path | None:
    d = (repo / path).parent
    while True:
        if (d / "go.mod").is_file():
            return d
        if d == repo or repo not in d.parents:
            return None
        d = d.parent


def _clear_reports(tool: Tool) -> None:
    """Tools writing a report file (gitleaks) must never have a previous run's report parsed as theirs."""
    if tool.name == "gitleaks":
        GITLEAKS_REPORT.unlink(missing_ok=True)


def _remaining(ctx: Ctx) -> float | None:
    return None if ctx.deadline is None else ctx.deadline - time.monotonic()


def run_tool(tool: Tool, ctx: Ctx, files: list[str]) -> tuple[str, list[dict], int, str]:
    started = time.perf_counter()
    timeout = ctx.timeout * tool.timeout_factor
    groups: list[tuple[Path, list[str], str]] = [(ctx.repo, files, "")]
    env = tool.env
    scratch: str | None = None
    if tool.isolated:
        scratch = tempfile.mkdtemp(prefix=f"hootpr-{tool.name}-")
        groups = [(Path(scratch), [str(ctx.repo / f) for f in files], "")]
        env = {**tool.env, "HOME": scratch}
    if tool.per_module:
        by_root: dict[Path, list[str]] = {}
        for f in files:
            root = _go_module_root(ctx.repo, f)
            if root is not None:
                by_root.setdefault(root, []).append(os.path.relpath(ctx.repo / f, root))
        groups = [(root, fs, os.path.relpath(root, ctx.repo)) for root, fs in by_root.items()]
        if not groups:
            return "skipped", [], 0, "no go.mod"
    found: list[dict] = []
    status, stderr = "ok", ""
    try:
        for cwd, fs, prefix in groups:
            left = _remaining(ctx)
            if left is not None and left <= 1:
                status, stderr = "timeout", "skipped: the static-analysis time budget was used up"
                continue
            limit = timeout if left is None else min(timeout, left)
            _clear_reports(tool)
            code, out, err, timed_out = _exec(tool.command(ctx, fs), cwd, limit, env)
            if code != 0 and tool.fallback is not None and not timed_out:
                left = _remaining(ctx)
                limit = timeout if left is None else max(1.0, min(timeout, left))
                _clear_reports(tool)
                code, out, err, timed_out = _exec(tool.fallback(ctx, fs), cwd, limit, env)
            if timed_out:
                status, stderr = "timeout", err
                continue
            if code in (EXEC_OVERFLOW, EXEC_NOSTART):
                status, stderr = "failed", err
                continue
            try:
                items = tool.parse(out, err, ctx)
            except (ValueError, KeyError, TypeError) as exc:
                status, stderr = "failed", f"exit {code}: {err or exc}"
                continue
            if code != 0 and not items and not out.strip():
                status, stderr = "failed", f"exit {code}: {err}"  # crashed before reporting anything
                continue
            if prefix and prefix != ".":
                for it in items:
                    it["path"] = posixpath.normpath(posixpath.join(prefix, it["path"]))
            found += items
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    return status, found, int((time.perf_counter() - started) * 1000), stderr[:STDERR_MAX]


def keep_relevant(items: list[dict], changed: set[str]) -> list[dict]:
    per_file: dict[str, int] = {}
    out = []
    for it in items:
        if it["path"] not in changed:
            continue
        n = per_file.get(it["path"], 0)
        if n >= MAX_PER_FILE:
            continue
        per_file[it["path"]] = n + 1
        out.append(it)
        if len(out) >= MAX_PER_TOOL:
            break
    return out


def run(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description="HootPR static tools (contract C1)")
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--changed", action="append", default=[])
    ap.add_argument("--enable", required=True)
    ap.add_argument("--base")
    ap.add_argument("--head")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--configs", type=Path, default=Path("/opt/hootpr/configs"))
    ap.add_argument("--phpstan-level", type=int, default=5)
    ap.add_argument("--semgrep-config")
    ap.add_argument("--manifest", action="append", default=[], help="lockfile scanned by trivy only")
    ap.add_argument("--deadline", type=float, default=None, help="total seconds for all tools; later tools are skipped")
    a = ap.parse_args(argv)
    started = time.monotonic()
    repo = a.repo.resolve()

    def present(paths: list[str]) -> list[str]:
        return [c.removeprefix("./") for c in paths if (repo / c.removeprefix("./")).is_file()]

    changed, manifests = present(a.changed), present(a.manifest)
    ctx = Ctx(
        repo,
        changed,
        a.configs.resolve(),
        a.timeout,
        a.base,
        a.head,
        a.phpstan_level,
        a.semgrep_config,
        manifests,
        None if a.deadline is None else started + a.deadline,
    )
    enabled = {t for t in a.enable.split(",") if t}
    runs, findings = [], []
    for tool in TOOLS:
        if tool.name not in enabled:
            continue
        files = select_files(tool, changed, manifests)
        if not files:
            runs.append(
                {"tool": tool.name, "status": "skipped", "duration_ms": 0, "findings_count": 0, "stderr_excerpt": ""}
            )
            continue
        if not tool.available():
            runs.append(
                {
                    "tool": tool.name,
                    "status": "unavailable",
                    "duration_ms": 0,
                    "findings_count": 0,
                    "stderr_excerpt": f"{tool.binary} not installed",
                }
            )
            continue
        status, items, ms, err = run_tool(tool, ctx, files)
        items = keep_relevant(items, set(changed) | (set(manifests) if tool.name == "trivy" else set()))
        runs.append(
            {
                "tool": tool.name,
                "status": status,
                "duration_ms": ms,
                "findings_count": len(items),
                "stderr_excerpt": err,
            }
        )
        findings += items
    return {"version": VERSION, "runs": runs, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    json.dump(run(argv), sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
