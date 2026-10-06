"""Image build step: make the ast-grep-essentials pack loadable by the pinned ast-grep (plan contract C4)."""

import importlib.util
import stat
from pathlib import Path
from types import ModuleType

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "build" / "sanitize_ast_grep_rules.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sanitize_ast_grep_rules", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BAD = """id: hardcoded-secret
language: python
severity: warning
message: >-
  Hardcoded secret.
utils:
  $DB(..., password="...",...):
    kind: call
    has:
      kind: string
  $DB(..., password="...",...)_with_Instance:
    kind: call
    inside:
      matches: $DB(..., password="...",...)
  plain_util:
    kind: identifier
rule:
  any:
    - matches: $DB(..., password="...",...)
    - matches: $DB(..., password="...",...)_with_Instance
    - all:
        - matches: plain_util
        - matches: global-util
"""
GOOD = """# comment kept: files that need no change are copied byte for byte
id: fine
language: go
message: ok
rule:
  pattern: fmt.Println($$$)
"""


def write_pack(root: Path) -> Path:
    src = root / "src"
    (src / "rules" / "python" / "security").mkdir(parents=True)
    (src / "rules" / "go" / "security").mkdir(parents=True)
    (src / "utils").mkdir()
    (src / "utils" / ".gitkeep").write_text("")
    (src / "rules" / "python" / "security" / "bad.yml").write_text(BAD)
    (src / "rules" / "go" / "security" / "good.yml").write_text(GOOD)
    (src / "rules" / "README.md").write_text("not a rule")
    return src


def test_util_ids_with_reserved_characters_are_renamed_consistently(tmp_path: Path) -> None:
    mod = load()
    src = write_pack(tmp_path)
    dst = tmp_path / "dst"
    stats = mod.sanitize(src, dst)
    doc = yaml.safe_load((dst / "rules" / "python" / "security" / "bad.yml").read_text())
    utils = doc["utils"]
    assert set(utils) == {"DB_password", "DB_password_with_Instance", "plain_util"}
    assert all(mod.VALID_ID.fullmatch(k) for k in utils)
    assert utils["DB_password_with_Instance"]["inside"] == {"matches": "DB_password"}
    assert doc["rule"]["any"][0] == {"matches": "DB_password"}
    assert doc["rule"]["any"][1] == {"matches": "DB_password_with_Instance"}
    # unknown ids (global utils from utilDirs) and already-valid ids are left alone
    assert doc["rule"]["any"][2] == {"all": [{"matches": "plain_util"}, {"matches": "global-util"}]}
    assert (doc["id"], doc["message"], doc["severity"]) == ("hardcoded-secret", "Hardcoded secret.", "warning")
    assert stats == {"rules": 2, "rewritten": 1, "dropped": 0}


def test_unchanged_rules_and_utils_are_copied_verbatim_and_non_rules_skipped(tmp_path: Path) -> None:
    mod = load()
    src = write_pack(tmp_path)
    dst = tmp_path / "dst"
    mod.sanitize(src, dst)
    assert (dst / "rules" / "go" / "security" / "good.yml").read_text() == GOOD
    assert (dst / "utils").is_dir()
    assert not (dst / "rules" / "README.md").exists()


def test_colliding_sanitized_ids_get_unique_suffixes(tmp_path: Path) -> None:
    mod = load()
    doc = {
        "utils": {"a b": {"kind": "x"}, "a(b)": {"kind": "y"}, "a_b": {"kind": "z"}},
        "rule": {"any": [{"matches": "a b"}, {"matches": "a(b)"}, {"matches": "a_b"}]},
    }
    assert mod.sanitize_doc(doc)
    assert list(doc["utils"]) == ["a_b_2", "a_b_3", "a_b"]
    assert doc["rule"]["any"] == [{"matches": "a_b_2"}, {"matches": "a_b_3"}, {"matches": "a_b"}]


def test_rules_the_validator_rejects_are_dropped(tmp_path: Path) -> None:
    mod = load()
    src = write_pack(tmp_path)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "ast-grep"
    # rejects any rule whose file mentions "fmt." (i.e. good.yml), accepts the rest
    fake.write_text(
        '#!/bin/sh\nfor d in $(sed -n "s/^- //p" "$3"); do grep -rq "fmt\\." "$d" && exit 2; done\nexit 0\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    dst = tmp_path / "dst"
    stats = mod.sanitize(src, dst, validator=str(fake))
    assert stats == {"rules": 1, "rewritten": 1, "dropped": 1}
    assert not (dst / "rules" / "go" / "security" / "good.yml").exists()
    assert (dst / "rules" / "python" / "security" / "bad.yml").exists()
