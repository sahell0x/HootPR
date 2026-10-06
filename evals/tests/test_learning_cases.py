import math
import shutil
from pathlib import Path

import pytest

from hootpr_evals.case import LEARNING_DATASETS, load_cases, load_learning_cases, materialize, validate_case
from hootpr_evals.embed import hash_embed


def test_learning_dataset_is_valid(tmp_path: Path) -> None:
    cases = load_learning_cases()
    assert {c.id for c in cases} == {"py-print-cli", "ts-any-in-tests", "go-errors-wrap", "py-auth-required"}
    for c in cases:
        assert c.learnings and any(i.learning_effect != "none" for i in c.issues)
        assert validate_case(c, materialize(c, tmp_path / c.id)) == []
        assert c.meta.config == {"reviews": {"profile": "assertive"}}


def test_learnings_yaml_is_parsed() -> None:
    [case] = load_learning_cases(only=["py-print-cli"])
    [entry] = case.learnings
    assert entry.scope == "repo" and entry.path_glob == "cli/**" and "print()" in entry.text


def test_regular_cases_default_to_no_learning_effect() -> None:
    cases = load_cases()
    assert all(i.learning_effect == "none" for c in cases for i in c.issues)
    assert all(c.learnings == () for c in cases)


def test_learning_case_requires_learnings(tmp_path: Path) -> None:
    dst = tmp_path / "py-print-cli"
    shutil.copytree(LEARNING_DATASETS / "py-print-cli", dst)
    (dst / "learnings.yaml").write_text("learnings: []\n")
    with pytest.raises(ValueError, match="learning"):
        load_learning_cases(tmp_path)


def test_learning_case_requires_an_affected_issue(tmp_path: Path) -> None:
    dst = tmp_path / "py-print-cli"
    shutil.copytree(LEARNING_DATASETS / "py-print-cli", dst)
    exp = dst / "expected.yaml"
    exp.write_text(exp.read_text().replace("learning_effect: suppress", "learning_effect: none"))
    with pytest.raises(ValueError, match="learning_effect"):
        load_learning_cases(tmp_path)


def test_learnings_yaml_rejects_unknown_keys(tmp_path: Path) -> None:
    dst = tmp_path / "py-print-cli"
    shutil.copytree(LEARNING_DATASETS / "py-print-cli", dst)
    (dst / "learnings.yaml").write_text("learnings:\n  - text: x\n    colour: red\n")
    with pytest.raises(ValueError):
        load_learning_cases(tmp_path)


def test_hash_embed_is_deterministic_and_similar_for_overlap() -> None:
    a, b, c = hash_embed(
        [
            "never flag print statements in cli",
            "task about print statements in cli/main.py",
            "golang rows.Err unchecked",
        ]
    )
    assert a == hash_embed(["never flag print statements in cli"])[0]
    assert len(a) == 64
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)

    def dot(u: list[float], v: list[float]) -> float:
        return sum(x * y for x, y in zip(u, v, strict=True))

    assert dot(a, b) > dot(a, c)


def test_hash_embed_handles_empty_text_and_custom_dims() -> None:
    [empty, v] = hash_embed(["", "the a of"], dims=8)  # only stopwords / short tokens
    assert empty == [0.0] * 8 and v == [0.0] * 8
    assert len(hash_embed(["hello world"], dims=1536)[0]) == 1536
