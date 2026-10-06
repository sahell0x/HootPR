"""AST-grep instructions (phase-3 R17, contract C4). Rules are YAML; nothing executes repo code.

Sources: ``reviews.ast_grep_instructions`` (inline rules in the configuration),
``reviews.tools.ast_grep.rule_dirs``/``util_dirs`` (rule YAML files read from the BASE commit, like
the configuration itself) and, with ``essential_rules``, the ast-grep-essentials pack baked into
the sandbox image. Matches on changed lines become instructions in the reviewer's context pack.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from app.config.schema import HootPRConfig
from app.review.stages.diff_filter import glob_match
from app.sandbox.base import Sandbox, UnsafePath, safe_relpath
from app.settings import Settings

ESSENTIALS_DIR = "/opt/hootpr/ast-grep/essentials"
WORK_SUBDIR = ".hootpr-astgrep"
MAX_RULE_FILES = 100
MAX_RULE_BYTES = 256 * 1024
RULE_FILE_MAX_KB = 64
SCAN_MAX_OUTPUT_KB = 4096
MAX_MATCHES = 500
MESSAGE_MAX_CHARS = 1000
# Written with the sandbox's Python: ``python -c WRITER <root> <base64-json {relpath: content}>``.
WRITER = (
    "import base64,json,os,sys\n"
    "root=sys.argv[1]\n"
    "for rel,body in json.loads(base64.b64decode(sys.argv[2])).items():\n"
    "    if rel.startswith('/') or '..' in rel.split('/'):\n"
    "        continue\n"
    "    p=os.path.join(root,rel)\n"
    "    os.makedirs(os.path.dirname(p),exist_ok=True)\n"
    "    with open(p,'w') as fh:\n"
    "        fh.write(body)\n"
)


@dataclass(frozen=True)
class AstGrepMatch:
    rule_id: str
    path: str
    line: int  # 1-based, new side
    end_line: int
    message: str  # as rendered by ast-grep: ``$VAR`` metavariables hold PR-head source text
    severity: str
    # The rule's own ``message`` from trusted configuration (inline rules / base-branch rule
    # files); ``None`` when unknown (e.g. the essentials pack).
    static_message: str | None = None

    def _span(self) -> str:
        if self.end_line == self.line:
            return f"line {self.line}"
        return f"lines {self.line}-{self.end_line}"

    def render(self) -> str:
        """Trusted instruction line: rule id, lines and the static message only."""
        text = self.static_message or "rule matched (details in the ast-grep block)"
        return f"{self._span()} [{self.rule_id}]: {text}"

    def untrusted_note(self) -> str | None:
        """The ast-grep-rendered message when it differs from the static one (may quote code)."""
        if self.message and self.message != self.static_message:
            return f"{self._span()} [{self.rule_id}]: {self.message}"
        return None


def static_messages(cfg: HootPRConfig, rule_files: Mapping[str, str]) -> dict[str, str]:
    """Rule id → message text as written in the trusted rule definitions."""
    out: dict[str, str] = {}
    for body in rule_files.values():
        try:
            docs = list(yaml.safe_load_all(body))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if isinstance(doc, dict) and isinstance(doc.get("id"), str):
                msg = doc.get("message")
                if isinstance(msg, str):
                    out[doc["id"]] = " ".join(msg.split())[:MESSAGE_MAX_CHARS]
    for r in cfg.reviews.ast_grep_instructions:
        out[r.id] = " ".join(r.message.split())[:MESSAGE_MAX_CHARS]
    return out


def inline_rule_files(cfg: HootPRConfig) -> dict[str, str]:
    """One ast-grep rule file per ``reviews.ast_grep_instructions`` entry.

    ``files`` globs are applied by :func:`parse_stream` (ast-grep resolves them against the
    project root, which is the rule workspace, not the repository)."""
    out: dict[str, str] = {}
    for r in cfg.reviews.ast_grep_instructions:
        doc: dict[str, object] = {
            "id": r.id,
            "language": r.language,
            "message": r.message,
            "severity": r.severity,
            "rule": r.rule,
        }
        out[f"rules/inline-{r.id}.yml"] = yaml.safe_dump(doc, sort_keys=False)
    return out


def repo_rule_files(
    sb: Sandbox, base_sha: str, dirs: Sequence[str], prefix: str
) -> tuple[dict[str, str], list[str]]:
    """``*.yml``/``*.yaml`` under ``dirs`` at ``base_sha`` → ``{prefix/NNN-name: content}``."""
    files: dict[str, str] = {}
    notes: list[str] = []
    total = 0
    for d in dirs:
        try:
            rel = safe_relpath(d.strip().rstrip("/"))
        except UnsafePath:
            notes.append(f"ast-grep rule dir skipped (unsafe path): {d}")
            continue
        r = sb.exec(
            ["git", "ls-tree", "-r", "-z", "--name-only", base_sha, "--", rel],
            timeout_s=30,
            max_output_kb=256,
        )
        if not r.ok:
            notes.append(f"ast-grep rule dir unreadable: {rel}")
            continue
        names = sorted(n for n in r.stdout.split("\0") if n.endswith((".yml", ".yaml")))
        for name in names:
            if len(files) >= MAX_RULE_FILES:
                notes.append(f"ast-grep rule files capped at {MAX_RULE_FILES}")
                return files, notes
            shown = sb.exec(
                ["git", "show", f"{base_sha}:{name}"], timeout_s=30, max_output_kb=RULE_FILE_MAX_KB
            )
            if not shown.ok or shown.truncated:
                notes.append(f"ast-grep rule file skipped: {name}")
                continue
            size = len(shown.stdout.encode())
            if total + size > MAX_RULE_BYTES:
                notes.append("ast-grep rule files over the size limit were skipped")
                return files, notes
            total += size
            files[f"{prefix}/{len(files):03d}-{PurePosixPath(name).name}"] = shown.stdout
    return files, notes


def sgconfig(rule_dirs: Sequence[str], util_dirs: Sequence[str]) -> str:
    doc: dict[str, list[str]] = {"ruleDirs": list(rule_dirs)}
    if util_dirs:
        doc["utilDirs"] = list(util_dirs)
    return yaml.safe_dump(doc, sort_keys=False)


def parse_stream(
    stdout: str,
    changed: Mapping[str, set[int] | None],
    *,
    rule_files: Mapping[str, Sequence[str]] | None = None,
    static_messages: Mapping[str, str] | None = None,
) -> list[AstGrepMatch]:
    """``--json=stream`` lines → matches overlapping changed lines (``None`` = whole file)."""
    out: list[AstGrepMatch] = []
    for raw in stdout.splitlines():
        try:
            m = json.loads(raw)
            path = str(m["file"]).removeprefix("./")
            start = int(m["range"]["start"]["line"]) + 1
            end = int(m["range"]["end"]["line"]) + 1
        except (ValueError, KeyError, TypeError):
            continue
        if path not in changed:
            continue
        lines = changed[path]
        if lines is not None and not any(start <= ln <= end for ln in lines):
            continue
        rule_id = str(m.get("ruleId") or "rule")
        globs = (rule_files or {}).get(rule_id)
        if globs and not any(glob_match(path, g) for g in globs):
            continue
        message = " ".join(str(m.get("message") or "").split())[:MESSAGE_MAX_CHARS]
        out.append(
            AstGrepMatch(
                rule_id,
                path,
                start,
                end,
                message,
                str(m.get("severity") or "warning"),
                (static_messages or {}).get(rule_id),
            )
        )
        if len(out) >= MAX_MATCHES:
            break
    return out


def _abs(root: str, dirs: Sequence[str]) -> list[str]:
    return [d if d.startswith("/") else f"{root}/{d}" for d in dirs]


def run_ast_grep(
    sb: Sandbox,
    cfg: HootPRConfig,
    base_sha: str,
    changed: Mapping[str, set[int] | None],
    settings: Settings,
) -> tuple[list[AstGrepMatch], str | None]:
    """Scan the changed files; (matches, degradation note or None)."""
    t = cfg.reviews.tools.ast_grep
    rules_cfg = cfg.reviews.ast_grep_instructions
    if not t.enabled or not changed or not (rules_cfg or t.rule_dirs or t.essential_rules):
        return [], None
    if not sb.exec(["ast-grep", "--version"], timeout_s=10, max_output_kb=4).ok:
        return [], "ast-grep unavailable"
    notes: list[str] = []
    files = inline_rule_files(cfg)
    repo_rules, n1 = repo_rule_files(sb, base_sha, t.rule_dirs, "rules/repo")
    utils, n2 = repo_rule_files(sb, base_sha, t.util_dirs, "utils/repo")
    notes += n1 + n2
    files |= repo_rules | utils
    rule_dirs = ["rules"] if (files.keys() - utils.keys()) else []
    util_dirs = ["utils"] if utils else []
    if t.essential_rules:
        ess_rules, ess_utils = f"{ESSENTIALS_DIR}/rules", f"{ESSENTIALS_DIR}/utils"
        if sb.exec(["test", "-d", ess_rules], timeout_s=5, max_output_kb=1).ok:
            rule_dirs.append(ess_rules)
            if sb.exec(["test", "-d", ess_utils], timeout_s=5, max_output_kb=1).ok:
                util_dirs.append(ess_utils)
        else:
            notes.append("essential rules unavailable")
    note = "; ".join(notes) or None
    if not rule_dirs:
        return [], note
    root = str(PurePosixPath(sb.repo_dir).parent / WORK_SUBDIR)
    files["sgconfig.yml"] = sgconfig(_abs(root, rule_dirs), _abs(root, util_dirs))
    payload = base64.b64encode(json.dumps(files).encode()).decode()
    w = sb.exec(
        [sb.python, "-c", WRITER, root, payload], timeout_s=30, max_output_kb=4, workdir="/"
    )
    if not w.ok:
        return [], "; ".join([*notes, "ast-grep rules could not be written"])
    r = sb.exec(
        [
            "ast-grep",
            "scan",
            "--config",
            f"{root}/sgconfig.yml",
            "--json=stream",
            "--",
            *sorted(changed),
        ],
        timeout_s=settings.ast_grep_timeout_s,
        max_output_kb=SCAN_MAX_OUTPUT_KB,
    )
    if r.timed_out:
        return [], "; ".join([*notes, "ast-grep timed out"])
    # ast-grep exits 1 when a rule with severity ``error`` matched.
    if r.exit_code not in (0, 1):
        return [], "; ".join([*notes, f"ast-grep exit {r.exit_code}"])
    if r.truncated:
        notes.append("ast-grep output truncated")
    globs = {x.id: tuple(x.files) for x in rules_cfg if x.files}
    msgs = static_messages(cfg, repo_rules)
    matches = parse_stream(r.stdout, changed, rule_files=globs, static_messages=msgs)
    return matches, "; ".join(notes) or None
