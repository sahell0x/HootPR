import json
from decimal import Decimal
from pathlib import Path

from hootpr_evals.case import ExpectedIssue
from hootpr_evals.matching import CaseMatch, ReviewFinding
from hootpr_evals.metrics import CaseResult, compute_metrics
from hootpr_evals.report import (
    EvalReport,
    RunReport,
    render_markdown,
    report_basename,
    to_json,
    update_readme,
    write_report,
)


def report(fake: bool = True) -> EvalReport:
    r = CaseResult(
        "py-sql-injection",
        "python",
        "injected",
        [],
        [],
        CaseMatch([], [], []),
        0,
        1200,
        0,
        300,
        Decimal("0.00042"),
        3.5,
        7,
    )
    runs = [RunReport("default", compute_metrics([r]), [r]), RunReport("judge_off", compute_metrics([r]), [r])]
    return EvalReport(
        "2026-09-29", "gpt-6-luna", "gpt-5-nano", "api.openai.com", "api.openai.com", fake, "docker", runs, ["note"]
    )


def test_markdown_has_summary_categories_cases_and_ablations() -> None:
    md = render_markdown(report())
    assert md.startswith("# HootPR eval — gpt-6-luna / gpt-5-nano (2026-09-29)")
    assert "fake LLM" in md and "| Precision | Recall | F1 |" in md
    assert "## Per case" in md and "py-sql-injection" in md
    assert "## Ablations" in md and "judge_off" in md
    assert "- Note: note" in md


def test_markdown_without_ablations_and_pipe_safe_errors() -> None:
    r = report(fake=False)
    r.runs = r.runs[:1]
    r.runs[0].results[0].error = "Boom: a|b\nsecond line"
    md = render_markdown(r)
    assert "## Ablations" not in md and "real LLM" in md
    assert "a\\|b second line" in md


def test_json_serializes_decimals_and_nested_models() -> None:
    iss = ExpectedIssue(id="i", path="a.py", line_range=(1, 2), category="bug", severity="major", description="d")
    f = ReviewFinding("a.py", None, 1, "bug", "major", "t", "b", 0.8)
    r = CaseResult(
        "c", "python", "injected", [iss], [f], CaseMatch([(0, "i")], [], []), 1, 1, 0, 1, Decimal("0.5"), 1.0, 1
    )
    rep = EvalReport(
        "2026-09-29", "m", "c", "h", "h", True, "local", [RunReport("default", compute_metrics([r]), [r])], []
    )
    data = json.loads(json.dumps(to_json(rep)))
    assert data["version"] == 1 and data["fake_llm"] is True
    case = data["runs"][0]["results"][0]
    assert case["cost_usd"] == "0.5" and case["expected"][0]["line_range"] == [1, 2]
    assert case["match"]["matched"] == [[0, "i"]]
    assert data["runs"][0]["metrics"]["per_category"]["bug"]["tp"] == 1


def test_write_report_and_readme_update(tmp_path: Path) -> None:
    r = report(fake=False)
    assert report_basename(r) == "2026-09-29-gpt-6-luna"
    assert report_basename(report(fake=True)) == "2026-09-29-gpt-6-luna-fake"
    md_path, json_path = write_report(r, tmp_path)
    assert (
        md_path.name == "2026-09-29-gpt-6-luna.md" and json.loads(json_path.read_text())["runs"][0]["name"] == "default"
    )
    readme = tmp_path / "README.md"
    readme.write_text(
        "x\n<!-- hootpr:eval-latest:start -->\nold\n<!-- hootpr:eval-latest:end -->\n"
        "<!-- hootpr:eval-history:start -->\n<!-- hootpr:eval-history:end -->\n"
    )
    update_readme(readme, r, md_path)
    update_readme(readme, r, md_path)
    text = readme.read_text()
    assert "old" not in text and text.count("| gpt-6-luna |") == 1
    assert text.count("reports/2026-09-29-gpt-6-luna.md") == 2  # latest link + one history line (idempotent)


def test_readme_history_keeps_older_runs_newest_first(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    first = report(fake=False)
    first.date = "2026-09-01"
    update_readme(readme, first, tmp_path / f"{report_basename(first)}.md")
    second = report(fake=False)
    update_readme(readme, second, tmp_path / f"{report_basename(second)}.md")
    text = readme.read_text()
    history = text[text.index("eval-history:start") :]
    assert history.index("2026-09-29-gpt-6-luna.md") < history.index("2026-09-01-gpt-6-luna.md")
    assert "2026-09-01" not in text[: text.index("eval-latest:end")]


def test_suite_readme_has_both_marker_blocks() -> None:
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    for marker in ("eval-latest:start", "eval-latest:end", "eval-history:start", "eval-history:end"):
        assert f"<!-- hootpr:{marker} -->" in text
