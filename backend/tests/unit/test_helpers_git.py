from pathlib import Path

from tests.helpers_git import git, make_git_repo


def test_make_git_repo_reports_every_status(tmp_path: Path) -> None:
    long = "".join(f"line {i}\n" for i in range(30))
    repo = make_git_repo(
        tmp_path,
        {"a.py": "x = 1\n", "gone.py": "z = 0\n", "old/name.py": long},
        {
            "a.py": "x = 2\n",
            "gone.py": None,
            "new.py": "y = 3\n",
            "old/name.py": None,
            "new/name.py": long,
        },
    )
    by_path = {f.path: f for f in repo.files}
    assert by_path["a.py"].status == "modified" and by_path["a.py"].changed_new_lines() == {1}
    assert by_path["gone.py"].status == "removed"
    assert by_path["new.py"].status == "added"
    assert by_path["new/name.py"].status == "renamed"
    assert by_path["new/name.py"].old_path == "old/name.py"
    assert git(repo.path, "rev-parse", "HEAD").strip() == repo.head_sha != repo.base_sha
