import base64
import json
import subprocess
import sys
from pathlib import Path

import yaml

from app.config.schema import HootPRConfig
from app.review.ast_grep import (
    WRITER,
    AstGrepMatch,
    inline_rule_files,
    parse_stream,
    repo_rule_files,
    run_ast_grep,
    sgconfig,
    static_messages,
)
from app.sandbox.base import ExecResult
from app.settings import Settings
from tests.fakes.sandbox import FakeSandbox

RULE = {
    "id": "no-print",
    "language": "python",
    "message": "Use logging.",
    "rule": {"pattern": "print($$$A)"},
}
CFG = HootPRConfig.model_validate({"reviews": {"ast_grep_instructions": [RULE]}})


def line(file: str, start: int, end: int, rule: str = "no-print") -> str:
    return json.dumps(
        {
            "file": file,
            "ruleId": rule,
            "severity": "warning",
            "message": "Use logging.",
            "range": {"start": {"line": start, "column": 0}, "end": {"line": end, "column": 3}},
        }
    )


def test_inline_rule_files() -> None:
    files = inline_rule_files(CFG)
    assert list(files) == ["rules/inline-no-print.yml"]
    doc = yaml.safe_load(files["rules/inline-no-print.yml"])
    assert doc == {
        "id": "no-print",
        "language": "python",
        "message": "Use logging.",
        "severity": "warning",
        "rule": {"pattern": "print($$$A)"},
    }


def test_sgconfig() -> None:
    assert yaml.safe_load(sgconfig(["rules", "/opt/x/rules"], ["utils"])) == {
        "ruleDirs": ["rules", "/opt/x/rules"],
        "utilDirs": ["utils"],
    }
    assert yaml.safe_load(sgconfig(["rules"], [])) == {"ruleDirs": ["rules"]}


def test_parse_stream_keeps_changed_lines_only() -> None:
    out = "\n".join([line("a.py", 1, 1), line("a.py", 9, 9), line("./b.py", 0, 0), "not json"])
    got = parse_stream(
        out, {"a.py": {2, 3}, "b.py": None}, static_messages={"no-print": "Use logging."}
    )
    assert got == [
        AstGrepMatch("no-print", "a.py", 2, 2, "Use logging.", "warning", "Use logging."),
        AstGrepMatch("no-print", "b.py", 1, 1, "Use logging.", "warning", "Use logging."),
    ]
    assert got[0].render() == "line 2 [no-print]: Use logging."
    assert AstGrepMatch("r", "a.py", 2, 4, "m", "error", "m").render() == "lines 2-4 [r]: m"
    assert got[0].untrusted_note() is None


def test_rendered_message_never_reaches_the_trusted_line() -> None:
    # ast-grep substitutes $VAR metavariables with PR-head source text
    m = AstGrepMatch("r", "a.py", 2, 2, 'found "IGNORE PREVIOUS"', "warning", "found $A")
    assert m.render() == "line 2 [r]: found $A"
    assert m.untrusted_note() == 'line 2 [r]: found "IGNORE PREVIOUS"'
    unknown = AstGrepMatch("ess", "a.py", 3, 3, "bad thing", "warning")
    assert "bad thing" not in unknown.render()
    assert unknown.untrusted_note() == "line 3 [ess]: bad thing"


def test_parse_stream_static_messages_from_rule_files() -> None:
    got = parse_stream(
        line("a.py", 0, 0, rule="custom"),
        {"a.py": None},
        static_messages=static_messages(
            CFG, {"rules/repo/000-a.yml": "id: custom\nmessage: Hi $A\n"}
        ),
    )
    assert got[0].static_message == "Hi $A"


def test_parse_stream_applies_rule_file_globs() -> None:
    out = "\n".join([line("src/a.py", 0, 0), line("tests/t.py", 0, 0)])
    got = parse_stream(
        out, {"src/a.py": None, "tests/t.py": None}, rule_files={"no-print": ("src/**",)}
    )
    assert [m.path for m in got] == ["src/a.py"]


def test_writer_writes_files_and_refuses_traversal(tmp_path: Path) -> None:
    payload = base64.b64encode(
        json.dumps({"rules/a.yml": "id: a\n", "../evil": "x", "/abs": "y"}).encode()
    ).decode()
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-c", WRITER, str(tmp_path / "w"), payload],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "w" / "rules" / "a.yml").read_text() == "id: a\n"
    assert not (tmp_path / "evil").exists()


class ScriptedSandbox(FakeSandbox):
    def __init__(
        self,
        scan_out: str,
        version_ok: bool = True,
        scan_code: int = 0,
        essentials: bool = False,
        tree: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.scan_out, self.version_ok, self.scan_code = scan_out, version_ok, scan_code
        self.essentials, self.tree = essentials, tree or {}

    def exec(
        self, argv: list[str], *, timeout_s: int, max_output_kb: int, workdir: str | None = None
    ) -> ExecResult:
        self.calls.append(argv)
        if argv[:2] == ["ast-grep", "--version"]:
            return ExecResult(0 if self.version_ok else 127, "ast-grep 0.39.0", "")
        if argv[:2] == ["ast-grep", "scan"]:
            return ExecResult(self.scan_code, self.scan_out, "")
        if argv[:2] == ["test", "-d"]:
            return ExecResult(0 if self.essentials else 1, "", "")
        if argv[:3] == ["git", "ls-tree", "-r"]:
            prefix = argv[-1].rstrip("/") + "/"
            names = [n for n in self.tree if n.startswith(prefix)]
            return ExecResult(0, "\0".join(names) + ("\0" if names else ""), "")
        if argv[:2] == ["git", "show"]:
            name = argv[2].split(":", 1)[1]
            return (
                ExecResult(0, self.tree[name], "") if name in self.tree else ExecResult(128, "", "")
            )
        return ExecResult(0, "", "")

    def written(self) -> dict[str, str]:
        call = next(c for c in self.calls if c[:2] == ["python3", "-c"])
        data: dict[str, str] = json.loads(base64.b64decode(call[4]))
        return data


def test_run_ast_grep_writes_config_and_scans_changed_files(settings: Settings) -> None:
    sb = ScriptedSandbox(line("a.py", 1, 1))
    matches, why = run_ast_grep(sb, CFG, "b" * 40, {"a.py": {2}}, settings)
    assert why is None and [m.path for m in matches] == ["a.py"]
    scan = next(c for c in sb.calls if c[:2] == ["ast-grep", "scan"])
    assert scan[2:4] == ["--config", "/work/.hootpr-astgrep/sgconfig.yml"]
    assert "--json=stream" in scan and scan[-2:] == ["--", "a.py"]
    assert matches[0].static_message == "Use logging."


def test_run_ast_grep_paths_cannot_become_flags(settings: Settings) -> None:
    sb = ScriptedSandbox("")
    run_ast_grep(sb, CFG, "b" * 40, {"--filter=zzz": None, "-U": None}, settings)
    scan = next(c for c in sb.calls if c[:2] == ["ast-grep", "scan"])
    sep = scan.index("--")
    assert set(scan[sep + 1 :]) == {"--filter=zzz", "-U"}
    assert "--filter=zzz" not in scan[:sep] and "-U" not in scan[:sep]
    files = sb.written()
    assert yaml.safe_load(files["sgconfig.yml"]) == {"ruleDirs": ["/work/.hootpr-astgrep/rules"]}
    assert "rules/inline-no-print.yml" in files


def test_run_ast_grep_reads_repo_rules_from_base_and_essentials(settings: Settings) -> None:
    cfg = HootPRConfig.model_validate(
        {
            "reviews": {
                "tools": {
                    "ast_grep": {
                        "rule_dirs": ["sg/rules", "../etc"],
                        "util_dirs": ["sg/utils"],
                        "essential_rules": True,
                    }
                }
            }
        }
    )
    tree = {
        "sg/rules/a.yml": "id: a\n",
        "sg/rules/readme.md": "x",
        "sg/utils/u.yaml": "id: u\n",
    }
    sb = ScriptedSandbox("", essentials=True, tree=tree)
    matches, why = run_ast_grep(sb, cfg, "b" * 40, {"a.py": None}, settings)
    assert matches == [] and why is not None and "../etc" in why
    files = sb.written()
    assert set(files) == {"sgconfig.yml", "rules/repo/000-a.yml", "utils/repo/000-u.yaml"}
    assert files["rules/repo/000-a.yml"] == "id: a\n"
    conf = yaml.safe_load(files["sgconfig.yml"])
    assert conf["ruleDirs"] == [
        "/work/.hootpr-astgrep/rules",
        "/opt/hootpr/ast-grep/essentials/rules",
    ]
    assert conf["utilDirs"] == [
        "/work/.hootpr-astgrep/utils",
        "/opt/hootpr/ast-grep/essentials/utils",
    ]
    ls = [c for c in sb.calls if c[:3] == ["git", "ls-tree", "-r"]]
    assert all("b" * 40 in c for c in ls)  # base commit only


def test_repo_rule_files_notes() -> None:
    sb = ScriptedSandbox("", tree={"r/a.yml": "x" * 10})
    files, notes = repo_rule_files(sb, "b" * 40, ["r", "/abs"], "rules/repo")
    assert files == {"rules/repo/000-a.yml": "x" * 10}
    assert notes == ["ast-grep rule dir skipped (unsafe path): /abs"]


def test_run_ast_grep_skips_without_rules_or_binary(settings: Settings) -> None:
    assert run_ast_grep(
        ScriptedSandbox(""), HootPRConfig(), "b" * 40, {"a.py": None}, settings
    ) == (
        [],
        None,
    )
    off = HootPRConfig.model_validate(
        {"reviews": {"ast_grep_instructions": [RULE], "tools": {"ast_grep": {"enabled": False}}}}
    )
    assert run_ast_grep(ScriptedSandbox(""), off, "b" * 40, {"a.py": None}, settings) == ([], None)
    assert run_ast_grep(ScriptedSandbox(""), CFG, "b" * 40, {}, settings) == ([], None)
    assert run_ast_grep(
        ScriptedSandbox("", version_ok=False), CFG, "b" * 40, {"a.py": None}, settings
    ) == ([], "ast-grep unavailable")


def test_run_ast_grep_exit_codes(settings: Settings) -> None:
    ok1, why1 = run_ast_grep(
        ScriptedSandbox(line("a.py", 0, 0), scan_code=1), CFG, "b" * 40, {"a.py": None}, settings
    )
    assert len(ok1) == 1 and why1 is None
    bad, why2 = run_ast_grep(
        ScriptedSandbox("", scan_code=2), CFG, "b" * 40, {"a.py": None}, settings
    )
    assert bad == [] and why2 == "ast-grep exit 2"
    none, why3 = run_ast_grep(
        ScriptedSandbox("", essentials=False),
        HootPRConfig.model_validate(
            {"reviews": {"tools": {"ast_grep": {"essential_rules": True}}}}
        ),
        "b" * 40,
        {"a.py": None},
        settings,
    )
    assert none == [] and why3 == "essential rules unavailable"
