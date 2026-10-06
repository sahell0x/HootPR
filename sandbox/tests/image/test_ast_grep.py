"""ast-grep in the hardened sandbox image (phase-3 R17, plan contract C4).

The backend writes `sgconfig.yml` + rule/util YAMLs under `/work/.hootpr-astgrep` and runs
`ast-grep scan --config … --json=stream <paths>` with the repo as cwd and no network. These tests do the
same with the production hardening flags. Skipped when Docker or the image is missing.
"""

import json
import subprocess
from pathlib import Path

import pytest
from image_helpers import HARDENING, IMAGE, _image_present, _readable

pytestmark = [
    pytest.mark.image,
    pytest.mark.skipif(not _image_present(), reason=f"docker or image {IMAGE} missing (make sandbox-image)"),
]
ESSENTIALS = "/opt/hootpr/ast-grep/essentials"
CFG_DIR = "/work/.hootpr-astgrep"
RULE = """id: no-print
language: python
message: Use logging instead of print().
severity: warning
rule:
  matches: print-call
"""
UTIL = """id: print-call
language: python
rule:
  pattern: print($$$ARGS)
"""
SGCONFIG = f"ruleDirs:\n- {CFG_DIR}/rules\nutilDirs:\n- {CFG_DIR}/utils\n"
ESSENTIALS_SGCONFIG = f"ruleDirs:\n- {ESSENTIALS}/rules\nutilDirs:\n- {ESSENTIALS}/utils\n"


def run(repo: Path, script: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run `script` in the image as the sandbox user, repo read-only at /work/repo (the cwd)."""
    _readable(repo)
    env_flags = [flag for k, v in env.items() for flag in ("-e", f"{k}={v}")]
    return subprocess.run(
        ["docker", "run", "--rm", *HARDENING, *env_flags, "-v", f"{repo}:/work/repo:ro", "-w", "/work/repo",
         "--entrypoint", "bash", IMAGE, "-c", script],
        capture_output=True, text=True, check=False, timeout=180,
    )  # fmt: skip


def matches(stdout: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_essentials_pack_is_baked_in_and_readable_by_the_sandbox_user(tmp_path: Path) -> None:
    script = (
        f"set -e; find {ESSENTIALS}/rules -name '*.yml' | wc -l; test -d {ESSENTIALS}/utils; "
        f"find {ESSENTIALS} ! -readable | wc -l; ast-grep --version"
    )
    r = run(tmp_path, script)
    assert r.returncode == 0, r.stderr
    rules, unreadable, version = r.stdout.splitlines()
    assert int(rules) >= 20
    assert int(unreadable) == 0
    assert version.startswith("ast-grep")
    major, minor = (int(x) for x in version.split()[-1].split(".")[:2])
    assert (major, minor) >= (0, 30)


def test_inline_rule_with_util_emits_stream_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def main():\n    print('hi')\n")
    (repo / "other.py").write_text("print('not scanned')\n")
    script = (
        f'set -e; mkdir -p {CFG_DIR}/rules {CFG_DIR}/utils; printf "%s" "$RULE" > {CFG_DIR}/rules/no-print.yml; '
        f'printf "%s" "$UTIL" > {CFG_DIR}/utils/print-call.yml; printf "%s" "$SG" > {CFG_DIR}/sgconfig.yml; '
        f"ast-grep scan --config {CFG_DIR}/sgconfig.yml --json=stream app.py || [ $? -eq 1 ]"
    )
    r = run(repo, script, RULE=RULE, UTIL=UTIL, SG=SGCONFIG)
    assert r.returncode == 0, r.stderr
    [match] = matches(r.stdout)
    assert (match["ruleId"], match["file"], match["severity"]) == ("no-print", "app.py", "warning")
    assert match["message"] == "Use logging instead of print()."
    rng = match["range"]
    assert isinstance(rng, dict)
    assert (rng["start"]["line"], rng["end"]["line"]) == (1, 1)


def test_essentials_scan_runs_offline_and_finds_a_known_issue(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tmp.py").write_text("import tempfile\n\npath = tempfile.mktemp()\n")
    (repo / "app.js").write_text("const crypto = require('crypto');\ncrypto.createHash('md5');\n")
    script = (
        f'set -e; mkdir -p {CFG_DIR}; printf "%s" "$SG" > {CFG_DIR}/sgconfig.yml; '
        f"ast-grep scan --config {CFG_DIR}/sgconfig.yml --json=stream tmp.py app.js || [ $? -eq 1 ]"
    )
    r = run(repo, script, SG=ESSENTIALS_SGCONFIG)
    assert r.returncode == 0, r.stderr
    found = matches(r.stdout)  # every line is one JSON match
    assert ("avoid-mktemp-python", "tmp.py", 2) in {
        (m["ruleId"], m["file"], m["range"]["start"]["line"])  # type: ignore[index]
        for m in found
    }
