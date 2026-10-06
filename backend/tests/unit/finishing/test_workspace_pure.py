import pytest

from app.finishing.workspace import (
    SuggestionEdit,
    is_junk,
    parse_name_status_z,
    parse_porcelain_z,
    plan_edits,
    plan_project,
    splice_lines,
)


def test_is_junk() -> None:
    assert is_junk("node_modules/x/index.js")
    assert is_junk("src/__pycache__/a.cpython-312.pyc")
    assert is_junk("pkg.egg-info/PKG-INFO")
    assert is_junk(".coverage")
    assert not is_junk("src/app.py")
    assert not is_junk("tests/test_app.py")


def test_parse_porcelain_z_handles_renames_and_untracked() -> None:
    out = " M a.py\0R  new.py\0old.py\0?? tests/test_x.py\0UU conflict.txt\0"
    assert parse_porcelain_z(out) == [
        (" M", "a.py"),
        ("R ", "new.py"),
        ("??", "tests/test_x.py"),
        ("UU", "conflict.txt"),
    ]


def test_parse_name_status_z() -> None:
    out = "M\0a.py\0A\0b.py\0D\0c.py\0R100\0old.py\0new.py\0"
    assert parse_name_status_z(out) == [
        ("M", "a.py"),
        ("A", "b.py"),
        ("D", "c.py"),
        ("D", "old.py"),
        ("A", "new.py"),
    ]


def test_splice_lines() -> None:
    text = "a\nb\nc\nd\n"
    assert splice_lines(text, 2, 3, "X") == "a\nX\nd\n"
    assert splice_lines(text, 4, 4, "Z\n") == "a\nb\nc\nZ\n"
    assert splice_lines(text, 1, 2, "") == "c\nd\n"
    with pytest.raises(ValueError):
        splice_lines(text, 3, 9, "x")


def test_plan_edits_bottom_up_and_skips_overlaps() -> None:
    edits = [
        SuggestionEdit("a.py", 1, 2, "x", "f1"),
        SuggestionEdit("a.py", 10, 12, "y", "f2"),
        SuggestionEdit("a.py", 11, 11, "z", "f3"),  # overlaps f2 (the lower one wins)
        SuggestionEdit("b.py", 5, 5, "w", "f4"),
    ]
    accepted, skipped = plan_edits(edits)
    assert [e.ref for e in accepted] == ["f3", "f1", "f4"]
    assert [e.ref for e in skipped] == ["f2"]


def test_plan_project_python_node_go() -> None:
    files = {
        "pyproject.toml",
        "src/app.py",
        "tests/test_app.py",
        "package.json",
        "yarn.lock",
        "go.mod",
        "x_test.go",
    }
    p = plan_project(files, {"scripts": {"test": "vitest run"}}, "/work")
    assert p.languages == ("python", "node", "go")
    assert "python3 -m venv /work/.venv" in p.install[0]
    assert "corepack yarn install --frozen-lockfile" in p.install
    assert (
        p.test
        == "python -m pytest -q -x -p no:cacheprovider && corepack yarn test && go test ./..."
    )


def test_plan_project_without_tests() -> None:
    p = plan_project(
        {"package.json"}, {"scripts": {"test": 'echo "Error: no test specified"'}}, "/w"
    )
    assert p.test is None and p.install == ("npm install --no-audit --no-fund",)
    assert plan_project({"README.md"}, None, "/w").test is None


def test_plan_project_loose_python_scripts() -> None:
    # No pyproject/requirements: still Python, and pytest runs once a test file exists.
    assert plan_project({"a.py"}, None, "/w").languages == ("python",)
    assert plan_project({"a.py"}, None, "/w").test is None
    assert plan_project({"a.py", "test_a.py"}, None, "/w").test is not None
