"""Run the real sandbox image with the production hardening flags (spec §4.3, §13 'Sandbox').

Built by `make test-sandbox` (which depends on `make sandbox-image`); skipped when Docker or the image
is missing so a plain `pytest sandbox/tests` on a machine without the image stays green.
"""

import json
import subprocess
from pathlib import Path

import pytest
from image_helpers import ALL_TOOLS, HARDENING, IMAGE, _image_present, _readable

pytestmark = [
    pytest.mark.image,
    pytest.mark.skipif(not _image_present(), reason=f"docker or image {IMAGE} missing (make sandbox-image)"),
]


def docker_run(repo: Path, *cmd: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    _readable(repo)
    return subprocess.run(
        ["docker", "run", "--rm", *HARDENING, "-v", f"{repo}:/work/repo:ro", IMAGE, *cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_image_size_is_under_3_gb() -> None:
    size = int(
        subprocess.run(
            ["docker", "image", "inspect", "-f", "{{.Size}}", IMAGE], capture_output=True, text=True, check=True
        ).stdout
    )
    assert size < 3 * 1024**3, f"{size / 1024**3:.2f} GB"


def test_image_runs_as_the_sandbox_user_with_a_work_volume() -> None:
    out = subprocess.run(
        ["docker", "image", "inspect", "-f", "{{.Config.User}} {{json .Config.Volumes}}", IMAGE],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.startswith("10001:10001 ") and '"/work"' in out, out


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "--version"],
        ["rg", "--version"],
        ["ast-grep", "--version"],
        ["python3", "--version"],
        ["semgrep", "--version"],
        ["gitleaks", "version"],
        ["trivy", "--version"],
        ["checkov", "--version"],
        ["ruff", "--version"],
        ["eslint", "--version"],
        ["shellcheck", "--version"],
        ["hadolint", "--version"],
        ["actionlint", "-version"],
        ["yamllint", "--version"],
        ["markdownlint", "--version"],
        ["golangci-lint", "--version"],
        ["go", "version"],
        ["rubocop", "--version"],
        ["php", "/opt/hootpr/bin/phpstan.phar", "--version"],
        ["swiftlint", "version"],
    ],
    ids=lambda a: a[0] if a[0] != "php" else "phpstan",
)
def test_every_tool_runs_as_the_sandbox_user(tmp_path: Path, argv: list[str]) -> None:
    r = docker_run(tmp_path, *argv, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_python3_loads_the_baked_tree_sitter_grammars_offline(tmp_path: Path) -> None:
    """build_graph.py runs with `python3`; grammars must load from the read-only image, never download."""
    langs = ["python", "javascript", "typescript", "tsx", "go", "java", "ruby", "php", "rust", "c", "cpp"]
    langs += ["csharp", "kotlin", "swift", "bash"]
    code = (
        "import sys, tree_sitter_language_pack as t\n"
        "for lang in sys.argv[1:]:\n"
        "    assert t.get_parser(lang).parse(b'x').root_node is not None, lang\n"
        "print('ok', len(sys.argv) - 1)\n"
    )
    r = docker_run(tmp_path, "python3", "-c", code, *langs, timeout=120)
    assert r.returncode == 0 and r.stdout.strip() == f"ok {len(langs)}", r.stdout + r.stderr


def test_run_tools_finds_known_issues_in_the_fixture(polyglot: Path) -> None:
    changed = [
        "app/unsafe.py",
        "app/settings.py",
        "web/api.ts",
        "scripts/run.sh",
        "Dockerfile",
        ".github/workflows/ci.yml",
        "config.yml",
        "README.md",
        "infra/main.tf",
        "go/main.go",
    ]
    head = subprocess.run(
        ["git", "-C", str(polyglot), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    base = subprocess.run(
        ["git", "-C", str(polyglot), "rev-parse", "HEAD~1"], capture_output=True, text=True, check=True
    ).stdout.strip()
    args = ["python3", "/opt/hootpr/tools/run_tools.py", "--repo", "/work/repo", "--base", base, "--head", head]
    args += ["--enable", ALL_TOOLS]
    for c in changed:
        args += ["--changed", c]
    r = docker_run(polyglot, *args)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    status = {x["tool"]: (x["status"], x["stderr_excerpt"]) for x in doc["runs"]}
    assert all(s == "ok" for s, _ in status.values()), status
    rules = {(f["tool"], f["rule_id"]) for f in doc["findings"]}
    tools_with_hits = {t for t, _ in rules}
    assert {
        "ruff",
        "eslint",
        "shellcheck",
        "hadolint",
        "yamllint",
        "markdownlint",
        "gitleaks",
        "semgrep",
        "actionlint",
        "checkov",
        "golangci_lint",
    } <= tools_with_hits, rules
    assert ("ruff", "S602") in rules and ("hadolint", "DL3007") in rules
    assert ("eslint", "no-eval") in rules
    assert ("semgrep", "python.lang.security.audit.subprocess-shell-true.subprocess-shell-true") in rules
    assert ("golangci_lint", "errcheck") in rules
    assert not [f for f in doc["findings"] if "hootpr-fixture-9f8e" in f["message"]], "secret leaked into output"


def test_build_graph_runs_in_the_image(polyglot: Path) -> None:
    r = docker_run(
        polyglot,
        "python3",
        "/opt/hootpr/tools/build_graph.py",
        "--repo",
        "/work/repo",
        "--changed",
        "app/service.py",
        timeout=300,
    )
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["scope"] == "full" and not doc["errors"], doc["errors"]
    assert any(s["qualified_name"] == "UserService.show" for s in doc["symbols"])
    assert any(s["path"] == "web/api.ts" and s["name"] == "Api" for s in doc["symbols"])
    assert any(s["path"] == "go/main.go" and s["name"] == "main" for s in doc["symbols"])


def test_repo_configs_that_execute_code_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "eslint.config.js").write_text("require('fs').writeFileSync('/tmp/pwned', 'x'); module.exports = [];\n")
    (tmp_path / "eslint.config.mjs").write_text(
        "import fs from 'fs'; fs.writeFileSync('/tmp/pwned', 'x'); export default [];\n"
    )
    (tmp_path / "a.js").write_text("eval(x)\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    r = docker_run(
        tmp_path,
        "sh",
        "-c",
        "python3 /opt/hootpr/tools/run_tools.py --repo /work/repo --changed a.js --enable eslint"
        " && test ! -e /tmp/pwned",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert {(f["tool"], f["rule_id"]) for f in doc["findings"]} >= {("eslint", "no-eval")}, doc


def test_root_filesystem_is_read_only_and_network_is_sealed(tmp_path: Path) -> None:
    r = docker_run(
        tmp_path,
        "sh",
        "-c",
        "! touch /opt/hootpr/x 2>/dev/null && ! touch /work/repo/x 2>/dev/null"
        " && mkdir -p /work/.hootpr && touch /work/.hootpr/ok && touch /tmp/ok"
        " && ! git ls-remote https://github.com/git/git >/dev/null 2>&1",
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_repo_files_that_tools_autoload_from_cwd_never_run(tmp_path: Path) -> None:
    """checkov (.checkov.yaml external checks), phpstan (vendor/autoload.php) and rubocop (.rubocop args)
    would run repository code if started from the checkout (spec §4.3)."""
    (tmp_path / ".rubocop").write_text("--require ./evil.rb\n")
    (tmp_path / "evil.rb").write_text("File.write('/tmp/pwned-rubocop', 'x')\n")
    (tmp_path / "a.rb").write_text("x = 1\nputs x\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "autoload.php").write_text("<?php file_put_contents('/tmp/pwned-php', 'x');\n")
    (tmp_path / "a.php").write_text("<?php\nfunction f() { return $x; }\n")
    (tmp_path / ".checkov.yaml").write_text("external-checks-dir:\n  - evil_checks\n")
    (tmp_path / "evil_checks").mkdir()
    (tmp_path / "evil_checks" / "__init__.py").write_text("open('/tmp/pwned-checkov', 'w').write('x')\n")
    (tmp_path / "evil_checks" / "check.py").write_text("open('/tmp/pwned-checkov', 'w').write('x')\n")
    (tmp_path / "Dockerfile").write_text("FROM ubuntu:latest\nRUN apt-get update\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    r = docker_run(
        tmp_path,
        "sh",
        "-c",
        "python3 /opt/hootpr/tools/run_tools.py --repo /work/repo --changed a.rb --changed a.php"
        " --changed Dockerfile --enable rubocop,phpstan,checkov"
        " && test ! -e /tmp/pwned-rubocop && test ! -e /tmp/pwned-php && test ! -e /tmp/pwned-checkov",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    status = {x["tool"]: x["status"] for x in doc["runs"]}
    assert status == {"checkov": "ok", "rubocop": "ok", "phpstan": "ok"}, doc["runs"]
    tools = {f["tool"] for f in doc["findings"]}
    assert {"rubocop", "phpstan", "checkov"} <= tools, doc["findings"]
