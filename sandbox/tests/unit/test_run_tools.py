import json
import os
import stat
from pathlib import Path

import pytest
import run_tools as rt


def ctx(repo: Path) -> rt.Ctx:
    return rt.Ctx(
        repo=repo,
        changed=["a.py"],
        configs=Path("/cfg"),
        timeout=10,
        base=None,
        head=None,
        phpstan_level=5,
        semgrep_config=None,
    )


def fake_bin(tmp_path: Path, name: str, script: str) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    p = bindir / name
    p.write_text("#!/bin/sh\n" + script)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return bindir


def test_relevance() -> None:
    by = {t.name: t for t in rt.TOOLS}
    changed = [
        "a.py",
        "web/x.tsx",
        "run.sh",
        "Dockerfile",
        ".github/workflows/ci.yml",
        "k.yaml",
        "README.md",
        "go/main.go",
        "lib/a.rb",
        "a.php",
        "a.swift",
        "infra/main.tf",
        "package-lock.json",
    ]
    assert rt.select_files(by["ruff"], changed) == ["a.py"]
    assert rt.select_files(by["eslint"], changed) == ["web/x.tsx"]
    assert rt.select_files(by["shellcheck"], changed) == ["run.sh"]
    assert rt.select_files(by["hadolint"], changed) == ["Dockerfile"]
    assert rt.select_files(by["actionlint"], changed) == [".github/workflows/ci.yml"]
    assert set(rt.select_files(by["yamllint"], changed)) == {".github/workflows/ci.yml", "k.yaml"}
    assert rt.select_files(by["markdownlint"], changed) == ["README.md"]
    assert rt.select_files(by["golangci_lint"], changed) == ["go/main.go"]
    assert "package-lock.json" in rt.select_files(by["trivy"], changed)
    assert "infra/main.tf" in rt.select_files(by["checkov"], changed)
    assert len(rt.TOOLS) == 15


SAMPLES = {
    "semgrep": (
        '{"results":[{"check_id":"python.lang.security.audit.subprocess-shell-true","path":"a.py",'
        '"start":{"line":4},"end":{"line":4},"extra":{"message":"shell=True","severity":"ERROR"}}]}',
        "",
    ),
    "ruff": (
        '[{"code":"S602","message":"subprocess call with shell=True","filename":"/r/a.py",'
        '"location":{"row":4,"column":1},"end_location":{"row":4,"column":9}}]',
        "",
    ),
    "eslint": (
        '[{"filePath":"/r/a.ts","messages":[{"ruleId":"no-eval","severity":2,"message":"eval can be harmful",'
        '"line":9,"endLine":9}]}]',
        "",
    ),
    "shellcheck": ('[{"file":"a.sh","line":3,"endLine":3,"level":"info","code":2086,"message":"Double quote"}]', ""),
    "hadolint": ('[{"file":"Dockerfile","line":1,"level":"warning","code":"DL3007","message":"Using latest"}]', ""),
    "actionlint": (
        '[{"message":"untrusted input","filepath":".github/workflows/ci.yml","line":6,"kind":"expression"}]',
        "",
    ),
    "yamllint": ("config.yml:1:6: [warning] too many spaces after colon (colons)\n", ""),
    "markdownlint": (
        "",
        '[{"fileName":"README.md","lineNumber":1,"ruleNames":["MD018","no-missing-space-atx"],'
        '"ruleDescription":"No space after hash","errorDetail":null}]',
    ),
    "golangci_lint": (
        '{"Issues":[{"FromLinter":"errcheck","Text":"Error return value not checked","Pos":'
        '{"Filename":"main.go","Line":6}},{"FromLinter":"typecheck","Text":"x","Pos":'
        '{"Filename":"main.go","Line":1}}]}',
        "",
    ),
    "rubocop": (
        '{"files":[{"path":"a.rb","offenses":[{"severity":"convention","message":"Use snake_case",'
        '"cop_name":"Naming/MethodName","location":{"start_line":2,"last_line":2}}]}]}',
        "",
    ),
    "phpstan": (
        '{"files":{"/r/a.php":{"messages":[{"message":"Undefined variable $x","line":3,'
        '"identifier":"variable.undefined"}]}}}',
        "",
    ),
    "swiftlint": (
        '[{"file":"/r/a.swift","line":1,"severity":"Warning","rule_id":"identifier_name","reason":"Too short"}]',
        "",
    ),
    "checkov": (
        '{"check_type":"terraform","results":{"failed_checks":[{"check_id":"CKV_AWS_20","check_name":'
        '"S3 public ACL","file_path":"/infra/main.tf","file_line_range":[1,4],"severity":null}]}}',
        "",
    ),
    "trivy": (
        '{"Results":[{"Target":"package-lock.json","Vulnerabilities":[{"VulnerabilityID":"CVE-1",'
        '"PkgName":"lodash","InstalledVersion":"4.17.0","FixedVersion":"4.17.21","Severity":"HIGH",'
        '"Title":"Prototype pollution"}]},{"Target":"infra/main.tf","Misconfigurations":[{"ID":"AVD-AWS-0092",'
        '"Title":"S3 ACL","Message":"public-read","Severity":"HIGH","CauseMetadata":{"StartLine":3,"EndLine":3}}]}]}',
        "",
    ),
}


@pytest.mark.parametrize("tool", sorted(SAMPLES))
def test_parsers_normalize(tool: str) -> None:
    out, err = SAMPLES[tool]
    parser = getattr(rt, f"parse_{tool}")
    items = parser(out, err, ctx(Path("/r")))
    assert items, tool
    for f in items:
        assert set(f) == {"tool", "rule_id", "path", "line", "end_line", "severity", "message"}
        assert f["tool"] == tool and f["severity"] in ("error", "warning", "info")
        assert not f["path"].startswith("/") and f["line"] >= 1
    if tool == "golangci_lint":
        assert [f["rule_id"] for f in items] == ["errcheck"]  # typecheck noise removed
    if tool == "trivy":
        assert {f["path"] for f in items} == {"package-lock.json", "infra/main.tf"}


def test_gitleaks_parser_reads_report_and_redacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = tmp_path / "gl.json"
    report.write_text(
        json.dumps(
            [
                {
                    "RuleID": "generic-api-key",
                    "Description": "Generic API Key",
                    "File": "app/settings.py",
                    "StartLine": 1,
                    "EndLine": 1,
                    "Secret": "REDACTED",
                }
            ]
        )
    )
    monkeypatch.setattr(rt, "GITLEAKS_REPORT", report)
    items = rt.parse_gitleaks("", "", ctx(tmp_path))
    assert items[0]["path"] == "app/settings.py" and "REDACTED" not in items[0]["message"]


def test_run_end_to_end_with_fake_binaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("import os\n")
    (repo / "b.md").write_text("#x\n")
    out = SAMPLES["ruff"][0].replace("/r/", f"{repo}/").replace('"row":4', '"row":1')
    bindir = fake_bin(tmp_path, "ruff", f"cat <<'EOF'\n{out}\nEOF\n")
    fake_bin(tmp_path, "shellcheck", "sleep 5\n")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    (repo / "s.sh").write_text("echo $1\n")
    doc = rt.run(
        [
            "--repo",
            str(repo),
            "--changed",
            "a.py",
            "--changed",
            "b.md",
            "--changed",
            "s.sh",
            "--changed",
            "gone.py",
            "--enable",
            "ruff,markdownlint,shellcheck,eslint",
            "--timeout",
            "1",
        ]
    )
    runs = {r["tool"]: r["status"] for r in doc["runs"]}
    assert runs == {"ruff": "ok", "markdownlint": "unavailable", "shellcheck": "timeout", "eslint": "skipped"}
    assert doc["version"] == 1 and doc["findings"][0]["path"] == "a.py" and doc["findings"][0]["rule_id"] == "S602"


def test_findings_outside_changed_files_are_dropped_and_capped() -> None:
    items = [
        {
            "tool": "ruff",
            "rule_id": "X",
            "path": "other.py",
            "line": 1,
            "end_line": 1,
            "severity": "info",
            "message": "m",
        }
    ] + [
        {
            "tool": "ruff",
            "rule_id": "X",
            "path": "a.py",
            "line": i + 1,
            "end_line": i + 1,
            "severity": "info",
            "message": "m",
        }
        for i in range(150)
    ]
    kept = rt.keep_relevant(items, {"a.py"})
    assert len(kept) == rt.MAX_PER_FILE and all(f["path"] == "a.py" for f in kept)


def test_bad_arguments_exit_2() -> None:
    with pytest.raises(SystemExit) as exc:
        rt.run([])
    assert exc.value.code == 2


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "configs" / "ruff.toml").exists(), reason="configs land in S3"
)
def test_real_ruff_on_host_if_present(tmp_path: Path) -> None:
    if not os.environ.get("PATH") or not __import__("shutil").which("ruff"):
        pytest.skip("ruff not on PATH")
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.py").write_text("import subprocess\nsubprocess.call('ls', shell=True)\n")
    cfg = Path(__file__).resolve().parents[2] / "configs"
    doc = rt.run(["--repo", str(repo), "--changed", "a.py", "--enable", "ruff", "--configs", str(cfg)])
    assert doc["runs"][0]["status"] == "ok"


def test_stale_gitleaks_report_is_never_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = tmp_path / "gl.json"
    report.write_text(json.dumps([{"RuleID": "old", "File": "a.py", "StartLine": 1}]))
    monkeypatch.setattr(rt, "GITLEAKS_REPORT", report)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    bindir = fake_bin(tmp_path, "gitleaks", "exit 0\n")  # writes no report
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    doc = rt.run(["--repo", str(repo), "--changed", "a.py", "--enable", "gitleaks"])
    assert doc["runs"][0]["status"] == "ok" and doc["findings"] == []


def test_unparseable_output_marks_tool_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    bindir = fake_bin(tmp_path, "ruff", "echo 'not json'; echo boom >&2; exit 2\n")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    doc = rt.run(["--repo", str(repo), "--changed", "a.py", "--enable", "ruff"])
    assert doc["runs"][0]["status"] == "failed" and "boom" in doc["runs"][0]["stderr_excerpt"]


def test_polyglot_fixture_every_tool_reports_a_valid_status(polyglot: Path) -> None:
    """Runs all 15 tools against the fixture with whatever binaries this host has (the image has all)."""
    changed = [
        "app/unsafe.py",
        "app/settings.py",
        "web/api.ts",
        "go/main.go",
        "scripts/run.sh",
        "Dockerfile",
        ".github/workflows/ci.yml",
        "infra/main.tf",
        "config.yml",
        "README.md",
    ]
    head = __import__("conftest").git(polyglot, "rev-parse", "HEAD")
    argv = [
        "--repo",
        str(polyglot),
        "--enable",
        ",".join(t.name for t in rt.TOOLS),
        "--base",
        f"{head}~1",
        "--head",
        head,
        "--timeout",
        "30",
        "--configs",
        str(Path(__file__).resolve().parents[2] / "configs"),
    ]
    for c in changed:
        argv += ["--changed", c]
    doc = rt.run(argv)
    runs = {r["tool"]: r for r in doc["runs"]}
    assert set(runs) == {t.name for t in rt.TOOLS}
    assert runs["rubocop"]["status"] == runs["phpstan"]["status"] == runs["swiftlint"]["status"] == "skipped"
    for r in runs.values():
        assert r["status"] in ("ok", "failed", "timeout", "skipped", "unavailable")
        assert len(r["stderr_excerpt"]) <= rt.STDERR_MAX
    for f in doc["findings"]:
        assert f["path"] in changed and f["severity"] in ("error", "warning", "info")
    json.dumps(doc)  # serializable


def test_cli_prints_one_json_document(polyglot: Path) -> None:
    import subprocess
    import sys

    tools = Path(__file__).resolve().parents[2] / "hootpr_tools"
    p = subprocess.run(
        [
            sys.executable,
            str(tools / "run_tools.py"),
            "--repo",
            str(polyglot),
            "--changed",
            "README.md",
            "--enable",
            "eslint",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 0
    assert json.loads(p.stdout)["runs"] == [
        {"tool": "eslint", "status": "skipped", "duration_ms": 0, "findings_count": 0, "stderr_excerpt": ""}
    ]
    bad = subprocess.run([sys.executable, str(tools / "run_tools.py"), "--repo", "x"], capture_output=True, check=False)
    assert bad.returncode == 2


def test_output_is_capped_while_streaming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    bindir = fake_bin(tmp_path, "ruff", "yes '[]' | head -c 200000\n")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setattr(rt, "MAX_OUTPUT_BYTES", 1000)
    doc = rt.run(["--repo", str(repo), "--changed", "a.py", "--enable", "ruff"])
    assert doc["runs"][0]["status"] == "failed"
    assert "output exceeded" in doc["runs"][0]["stderr_excerpt"]


def test_timeout_kills_the_whole_process_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    marker = tmp_path / "survived"
    bindir = fake_bin(tmp_path, "ruff", f"(sleep 2; touch {marker}) &\nsleep 30\n")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    import time

    started = time.monotonic()
    doc = rt.run(["--repo", str(repo), "--changed", "a.py", "--enable", "ruff", "--timeout", "1"])
    assert doc["runs"][0]["status"] == "timeout" and time.monotonic() - started < 5
    time.sleep(2.5)
    assert not marker.exists()


def test_crash_without_output_is_failed_not_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    bindir = fake_bin(tmp_path, "ruff", "echo 'ruff failed: config not found' >&2; exit 2\n")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    doc = rt.run(["--repo", str(repo), "--changed", "a.py", "--enable", "ruff"])
    assert doc["runs"][0]["status"] == "failed" and "config not found" in doc["runs"][0]["stderr_excerpt"]


def test_golangci_lint_uses_the_v2_cli_without_repo_config() -> None:
    """The image ships golangci-lint v2 (v1 cannot load modules declaring newer Go versions)."""
    cmd = rt.c_golangci_lint(ctx(Path("/r")), ["main.go", "store/store.go"])
    assert cmd[:3] == ["golangci-lint", "run", "--no-config"]
    assert "--default=none" in cmd and "--output.json.path=stdout" in cmd and "--show-stats=false" in cmd
    assert "--disable-all" not in cmd and "--out-format" not in cmd
    enabled = {cmd[i + 1] for i, a in enumerate(cmd) if a == "-E"}
    assert enabled == {"govet", "errcheck", "staticcheck", "ineffassign", "unused", "gosec"}
    assert cmd[-2:] == ["./.", "./store"]


def test_trivy_reads_the_baked_db_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The image's DB (~1.4 GB) is opened read-only with an in-memory scan cache: never copied per review."""
    baked = tmp_path / "trivy-cache"
    (baked / "db").mkdir(parents=True)
    baked.chmod(0o555)
    monkeypatch.setattr(rt, "TRIVY_CACHE", str(baked))
    monkeypatch.setattr(rt, "WORK_CACHE", tmp_path / "work")
    cmd = rt.c_trivy(ctx(tmp_path), ["requirements.txt"])
    assert cmd[cmd.index("--cache-dir") + 1] == str(baked)
    assert cmd[cmd.index("--cache-backend") + 1] == "memory"
    assert not (tmp_path / "work").exists()


def test_semgrep_rule_ids_drop_the_local_config_path_prefix() -> None:
    """semgrep prefixes ids of rules loaded from a local file with its directory (opt.hootpr.configs.semgrep.)."""
    c = rt.Ctx(Path("/r"), ["a.py"], Path("/opt/hootpr/configs"), 10, None, None, 5, None)
    out = json.dumps(
        {
            "results": [
                {
                    "check_id": "opt.hootpr.configs.semgrep.python.lang.security.audit.subprocess-shell-true",
                    "path": "/r/a.py",
                    "start": {"line": 5},
                    "end": {"line": 5},
                    "extra": {"message": "shell=True", "severity": "ERROR"},
                }
            ]
        }
    )
    [f] = rt.parse_semgrep(out, "", c)
    assert f["rule_id"] == "python.lang.security.audit.subprocess-shell-true" and f["path"] == "a.py"


TRIVY_OUT = json.dumps(
    {
        "Results": [
            {
                "Target": "poetry.lock",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2024-0001",
                        "PkgName": "requests",
                        "InstalledVersion": "2.0.0",
                        "FixedVersion": "2.32.0",
                        "Severity": "HIGH",
                        "Title": "bad",
                    }
                ],
            }
        ]
    }
)


def test_lockfiles_passed_as_manifests_feed_trivy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lockfiles are never reviewed line by line, but trivy must still report their vulnerable deps."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / "poetry.lock").write_text("[[package]]\n")
    bindir = fake_bin(tmp_path, "trivy", f"cat <<'EOF'\n{TRIVY_OUT}\nEOF\n")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setattr(rt, "WORK_CACHE", tmp_path / "work")
    base = ["--repo", str(repo), "--changed", "a.py", "--enable", "trivy"]
    assert rt.run(base)["runs"][0]["status"] == "skipped"
    doc = rt.run([*base, "--manifest", "poetry.lock"])
    assert doc["runs"][0]["status"] == "ok"
    assert [(f["path"], f["rule_id"]) for f in doc["findings"]] == [("poetry.lock", "CVE-2024-0001")]


def test_global_deadline_skips_remaining_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole run must finish (and print JSON) before the engine's outer timeout kills it."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / "s.sh").write_text("echo hi\n")
    bindir = fake_bin(tmp_path, "ruff", "sleep 30\n")
    fake_bin(tmp_path, "shellcheck", "echo '[]'\n")
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    started = time.monotonic()
    doc = rt.run(
        [
            *["--repo", str(repo), "--changed", "a.py", "--changed", "s.sh", "--enable", "ruff,shellcheck"],
            *["--timeout", "60", "--deadline", "2"],
        ]
    )
    assert time.monotonic() - started < 6
    runs = {r["tool"]: r for r in doc["runs"]}
    assert runs["ruff"]["status"] == "timeout"
    assert runs["shellcheck"]["status"] == "timeout" and "budget" in runs["shellcheck"]["stderr_excerpt"]


def test_isolated_tools_run_outside_the_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rubocop/phpstan/checkov auto-load code-executing files from the cwd (.rubocop, vendor/, .checkov.yaml)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.rb").write_text("x = 1\n")
    log = tmp_path / "log"
    bindir = fake_bin(
        tmp_path,
        "rubocop",
        f'echo "cwd=$(pwd) home=$HOME opts=$RUBOCOP_OPTS args=$*" > {log}\necho \'{{"files":[]}}\'\n',
    )
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setenv("RUBOCOP_OPTS", "--require ./evil.rb")
    doc = rt.run(["--repo", str(repo), "--changed", "a.rb", "--enable", "rubocop"])
    assert doc["runs"][0]["status"] == "ok"
    seen = log.read_text()
    cwd = seen.split("cwd=")[1].split()[0]
    assert not cwd.startswith(str(repo)) and f"home={cwd}" in seen
    assert "opts= " in seen and f"{repo}/a.rb" in seen
    assert not Path(cwd).exists()  # scratch dir removed
    assert {t.name for t in rt.TOOLS if t.isolated} == {"checkov", "rubocop", "phpstan"}
