from pathlib import Path

import pytest
import yaml

from hootpr_evals.case import load_case, load_cases, materialize, validate_case


def write_case(
    root: Path, cid: str = "py-demo", *, issues: list[dict[str, object]] | None = None, kind: str = "injected"
) -> Path:
    d = root / cid
    (d / "base" / "app").mkdir(parents=True)
    (d / "head" / "app").mkdir(parents=True)
    (d / "base" / "app" / "a.py").write_text("def f(x):\n    return x\n")
    (d / "head" / "app" / "a.py").write_text("def f(x):\n    return x\n\n\ndef g(q):\n    return eval(q)\n")
    (d / "base" / "old.py").write_text("gone = True\n")
    (d / "case.yaml").write_text(
        yaml.safe_dump({"id": cid, "language": "python", "kind": kind, "title": "Add g", "deleted": ["old.py"]})
    )
    default = [
        {
            "id": "eval",
            "path": "app/a.py",
            "line_range": [6, 6],
            "category": "security",
            "severity": "critical",
            "description": "eval of user input",
        }
    ]
    (d / "expected.yaml").write_text(yaml.safe_dump({"issues": default if issues is None else issues}))
    return d


def test_load_and_materialize(tmp_path: Path) -> None:
    case = load_case(write_case(tmp_path / "cases"))
    assert case.id == "py-demo" and case.issues[0].line_range == (6, 6)
    mat = materialize(case, tmp_path / "work")
    assert mat.base_sha != mat.head_sha and (mat.path / ".git").is_dir()
    by_path = {f.path: f for f in mat.files}
    assert by_path["app/a.py"].status == "modified" and 6 in by_path["app/a.py"].changed_new_lines()
    assert by_path["old.py"].status == "removed" and not (mat.path / "old.py").exists()
    assert validate_case(case, mat) == []


def test_materialize_is_deterministic(tmp_path: Path) -> None:
    case = load_case(write_case(tmp_path / "cases"))
    a = materialize(case, tmp_path / "w1")
    b = materialize(case, tmp_path / "w2")
    assert (a.base_sha, a.head_sha) == (b.base_sha, b.head_sha)


def test_validation_catches_bad_anchors_and_clean_cases_with_issues(tmp_path: Path) -> None:
    bad = load_case(
        write_case(
            tmp_path / "c1",
            issues=[
                {
                    "id": "x",
                    "path": "app/a.py",
                    "line_range": [1, 9],
                    "category": "bug",
                    "severity": "minor",
                    "description": "d",
                }
            ],
        )
    )
    errs = validate_case(bad, materialize(bad, tmp_path / "w1"))
    assert any("single hunk" in e for e in errs)
    clean = load_case(write_case(tmp_path / "c2", kind="clean"))
    assert any("clean" in e for e in validate_case(clean, materialize(clean, tmp_path / "w2")))
    missing = load_case(
        write_case(
            tmp_path / "c3",
            issues=[
                {
                    "id": "y",
                    "path": "nope.py",
                    "line_range": [1, 1],
                    "category": "bug",
                    "severity": "minor",
                    "description": "d",
                }
            ],
        )
    )
    assert any("not in the diff" in e for e in validate_case(missing, materialize(missing, tmp_path / "w3")))


def test_bad_line_range_is_rejected(tmp_path: Path) -> None:
    d = write_case(
        tmp_path / "cases",
        issues=[
            {
                "id": "x",
                "path": "app/a.py",
                "line_range": [5, 2],
                "category": "bug",
                "severity": "minor",
                "description": "d",
            }
        ],
    )
    with pytest.raises(ValueError, match="line_range"):
        load_case(d)


def test_load_cases_filters_and_rejects_unknown(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    write_case(root, "py-a")
    write_case(root, "py-b")
    assert [c.id for c in load_cases(root)] == ["py-a", "py-b"]
    assert [c.id for c in load_cases(root, ["py-b"])] == ["py-b"]
    with pytest.raises(ValueError, match="unknown case"):
        load_cases(root, ["nope"])


def test_case_id_must_match_directory(tmp_path: Path) -> None:
    d = write_case(tmp_path / "cases", "py-x")
    (d / "case.yaml").write_text(yaml.safe_dump({"id": "other", "language": "python", "kind": "clean", "title": "t"}))
    with pytest.raises(ValueError, match="directory"):
        load_case(d)
