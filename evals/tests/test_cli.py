"""CLI over the production engine (contract C2). Skips until backend package B4 lands."""

from pathlib import Path

import pytest

pytest.importorskip("app.review.engine")

from hootpr_evals.cli import main


def test_fake_run_writes_report_and_updates_readme(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("<!-- hootpr:eval-latest:start -->\n<!-- hootpr:eval-latest:end -->\n")
    code = main(
        [
            "--fake-llm",
            "--cases",
            "py-sql-injection,go-clean",
            "--sandbox",
            "local",
            "--ablations",
            "judge_off",
            "--reports-dir",
            str(tmp_path / "reports"),
            "--readme",
            str(readme),
            "--env-file",
            str(tmp_path / "none.env"),
        ]
    )
    assert code == 0
    md = next((tmp_path / "reports").glob("*-fake.md")).read_text()
    assert "## Ablations" in md and "judge_off" in md and "py-sql-injection" in md
    assert "Latest: [" in readme.read_text()


def test_learnings_suite_fake_run_writes_the_learnings_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hootpr_evals import runner
    from tests.test_learnings_runner import fake_engine

    monkeypatch.setattr(runner, "ENGINE", fake_engine)
    readme = tmp_path / "README.md"
    readme.write_text("# evals\n")
    code = main(
        [
            "--suite", "learnings", "--fake-llm", "--sandbox", "local", "--ablations", "judge_off",
            "--reports-dir", str(tmp_path / "reports"), "--readme", str(readme),
            "--env-file", str(tmp_path / "none.env"),
        ]
    )  # fmt: skip
    assert code == 0
    [md] = list((tmp_path / "reports").glob("*-learnings.md"))
    assert "| Suppression rate | 100.0% |" in md.read_text()
    assert "<!-- learnings:start -->" in readme.read_text()
    assert not list((tmp_path / "reports").glob("*-fake.md"))  # the review suite did not run


def test_learnings_suite_no_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hootpr_evals import runner
    from tests.test_learnings_runner import fake_engine

    monkeypatch.setattr(runner, "ENGINE", fake_engine)
    code = main(["--suite", "learnings", "--fake-llm", "--sandbox", "local", "--no-readme",
                 "--reports-dir", str(tmp_path), "--cases", "py-auth-required",
                 "--env-file", str(tmp_path / "none.env")])  # fmt: skip
    assert code == 0 and len(list(tmp_path.glob("*-learnings.md"))) == 1
