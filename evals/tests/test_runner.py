"""End-to-end over the production engine (contract C2). Skips until backend package B4 lands."""

from pathlib import Path

import pytest

pytest.importorskip("app.review.engine")  # contract C2: needs backend package B4

from app.settings import Settings

from hootpr_evals.case import DATASETS, load_cases
from hootpr_evals.metrics import compute_metrics
from hootpr_evals.runner import (
    RunOptions,
    oracle_llm_factory,
    oracle_matcher_factory,
    run_case,
    run_suite,
)

SETTINGS = Settings(_env_file=None, sandbox_backend="local")


def test_oracle_run_of_three_cases_scores_perfectly(tmp_path: Path) -> None:
    cases = load_cases(DATASETS, ["py-sql-injection", "ts-xss", "go-clean"])
    results = run_suite(
        cases,
        RunOptions(SETTINGS),
        oracle_llm_factory(SETTINGS),
        oracle_matcher_factory(),
        tmp_path,
        progress=lambda s: None,
    )
    m = compute_metrics(results)
    assert [r.error for r in results] == [None, None, None]
    assert (m.precision, m.recall, m.clean_fp_rate) == (1.0, 1.0, 0.0)
    # triage, plan, agent, summary (+ judge when there is a finding to verify)
    assert all(r.input_tokens > 0 and r.llm_calls >= (5 if r.expected else 4) for r in results)


def test_full_dataset_runs_end_to_end_with_the_fake_llm(tmp_path: Path) -> None:
    cases = load_cases(DATASETS)
    results = run_suite(
        cases,
        RunOptions(SETTINGS),
        oracle_llm_factory(SETTINGS),
        oracle_matcher_factory(),
        tmp_path,
        progress=lambda s: None,
    )
    m = compute_metrics(results)
    assert m.errors == 0 and m.recall == 1.0 and m.precision == 1.0, [(r.case_id, r.match, r.error) for r in results]


def test_noise_is_filtered_by_the_judge_but_not_without_it(tmp_path: Path) -> None:
    case = load_cases(DATASETS, ["py-sql-injection"])[0]
    with_judge = run_case(
        case, RunOptions(SETTINGS), oracle_llm_factory(SETTINGS, noise=True), oracle_matcher_factory(), tmp_path / "a"
    )
    no_judge = run_case(
        case,
        RunOptions(SETTINGS, ablation_name="judge_off"),
        oracle_llm_factory(SETTINGS, noise=True),
        oracle_matcher_factory(),
        tmp_path / "b",
    )
    assert len(with_judge.findings) == 1 and len(no_judge.findings) == 2
