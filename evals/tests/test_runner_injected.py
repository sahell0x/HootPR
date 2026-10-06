"""Runner + CLI over an injected engine function: exercises the oracle through the real Phase 1
LLMGateway, materialization, matching, metrics and reports without needing the backend engine (C2)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from app.llm.types import TraceContext
from app.settings import Settings
from pydantic import BaseModel

from hootpr_evals import runner
from hootpr_evals.case import DATASETS, load_cases
from hootpr_evals.cli import main
from hootpr_evals.metrics import compute_metrics
from hootpr_evals.runner import (
    ABLATIONS,
    EngineCall,
    RunOptions,
    choose_sandbox,
    oracle_llm_factory,
    oracle_matcher_factory,
    run_case,
    run_suite,
)

SETTINGS = Settings(_env_file=None, sandbox_backend="local")


class TriageFile(BaseModel):
    path: str
    decision: str
    summary: str


class TriageResult(BaseModel):
    files: list[TriageFile]


class Verdict(BaseModel):
    index: int
    verdict: str
    reason: str
    adjusted_severity: str | None


class JudgeBatch(BaseModel):
    verdicts: list[Verdict]


@dataclass
class Cand:
    path: str
    start_line: int | None
    end_line: int
    severity: str
    category: str
    title: str
    body: str
    confidence: float


@dataclass
class Outcome:
    inline: list[Cand]
    additional: list[Cand]


def mini_engine(call: EngineCall) -> Outcome:
    """A stand-in for run_engine speaking contract C3 to the LLM: triage, one agent task, judge."""
    files = "\n".join(f"### FILE {f.path}" for f in call.mat.files)
    call.llm.complete(
        "cheap",
        [{"role": "user", "content": files}],
        response_model=TriageResult,
        max_output_tokens=500,
        trace=TraceContext(),
    )
    tool = {"type": "function", "function": {"name": "done", "parameters": {"type": "object", "properties": {}}}}
    res = call.llm.complete(
        "review",
        [{"role": "system", "content": "[hootpr:agent]"}, {"role": "user", "content": f'<task ordinal="0">\n{files}'}],
        tools=[tool],
        max_output_tokens=500,
        trace=TraceContext(),
    )
    cands = [
        Cand(**{k: a[k] for k in Cand.__dataclass_fields__})
        for a in (json.loads(tc.arguments) for tc in res.tool_calls if tc.name == "report_finding")
    ]
    if call.ablation.get("judge", True) and cands:
        blocks = "\n".join(
            f"### FINDING {i}\npath: {c.path}\nlines: {c.start_line}-{c.end_line}" for i, c in enumerate(cands)
        )
        call.llm.complete(
            "review",
            [{"role": "user", "content": blocks}],
            response_model=JudgeBatch,
            max_output_tokens=500,
            trace=TraceContext(),
        )
        cands = [c for c in cands if c.confidence >= 0.6]
    return Outcome(inline=cands, additional=[])


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ENGINE", mini_engine)


def test_ablations_map_to_c2_ablation_kwargs() -> None:
    assert ABLATIONS["default"] == {}
    assert ABLATIONS["judge_off"] == {"judge": False}
    assert ABLATIONS["tools_off"] == {"tools": False}
    assert [ABLATIONS[f"steps_{n}"] for n in (0, 4, 8)] == [{"agent_max_steps": n} for n in (0, 4, 8)]


def test_choose_sandbox_honours_an_explicit_kind() -> None:
    kind, note = choose_sandbox(SETTINGS, "local")
    assert kind == "local" and note is not None and "shell" in note
    assert choose_sandbox(SETTINGS, "docker") == ("docker", None)


def test_auto_never_falls_back_to_the_host_for_real_llm_runs() -> None:
    import pytest

    from hootpr_evals.runner import SandboxChoiceError

    missing = Settings(_env_file=None, sandbox_backend="local", sandbox_image="hootpr/does-not-exist:none")
    with pytest.raises(SandboxChoiceError):
        choose_sandbox(missing, "auto", fake_llm=False)
    assert choose_sandbox(missing, "auto", fake_llm=True)[0] == "local"


def test_local_sandbox_runs_the_engine_without_the_shell_tool(tmp_path: Path) -> None:
    """Real engine, local sandbox: the agent's tool list never includes `shell`."""
    from hootpr_evals import runner

    seen: list[bool] = []
    real = runner.run_production_engine

    def spy(call: EngineCall) -> object:
        import app.review.engine as engine_mod

        orig = engine_mod.run_engine

        def wrapped(inputs: object, deps: object) -> object:
            seen.append(deps.agent_shell)  # type: ignore[attr-defined]
            return orig(inputs, deps)  # type: ignore[arg-type]

        engine_mod.run_engine = wrapped  # type: ignore[assignment]
        try:
            return real(call)
        finally:
            engine_mod.run_engine = orig

    case = load_cases(DATASETS)[0]
    old = runner.ENGINE
    runner.ENGINE = spy  # type: ignore[assignment]
    try:
        run_case(case, RunOptions(SETTINGS), oracle_llm_factory(SETTINGS), oracle_matcher_factory(), tmp_path)
    finally:
        runner.ENGINE = old
    assert seen == [False]


def test_full_dataset_through_the_oracle_and_gateway_scores_perfectly(engine: None, tmp_path: Path) -> None:
    cases = load_cases(DATASETS)
    assert len(cases) >= 12
    results = run_suite(
        cases,
        RunOptions(SETTINGS),
        oracle_llm_factory(SETTINGS),
        oracle_matcher_factory(),
        tmp_path,
        progress=lambda s: None,
    )
    m = compute_metrics(results)
    assert m.errors == 0, [r.error for r in results]
    assert (m.precision, m.recall, m.clean_fp_rate) == (1.0, 1.0, 0.0)
    assert all(r.input_tokens > 0 and r.llm_calls >= 2 for r in results)
    assert all(r.inline_count == len(r.expected) for r in results)


def test_ablation_reaches_the_engine_and_noise_needs_the_judge(engine: None, tmp_path: Path) -> None:
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
    assert len(no_judge.match.false_positives) == 1


def test_an_engine_crash_is_recorded_and_the_suite_continues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(call: EngineCall) -> Any:
        raise RuntimeError("sandbox exploded")

    monkeypatch.setattr(runner, "ENGINE", boom)
    cases = load_cases(DATASETS, ["py-sql-injection", "go-clean"])
    results = run_suite(
        cases,
        RunOptions(SETTINGS),
        oracle_llm_factory(SETTINGS),
        oracle_matcher_factory(),
        tmp_path,
        progress=lambda s: None,
    )
    assert [r.error for r in results] == ["RuntimeError: sandbox exploded"] * 2
    assert results[0].match.missed == [i.id for i in cases[0].issues]


def test_cli_fake_run_writes_report_with_ablations_and_updates_readme(engine: None, tmp_path: Path) -> None:
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
    assert next((tmp_path / "reports").glob("*-fake.json")).is_file()
    assert "Latest: [" in readme.read_text()


def test_cli_exit_code_1_when_every_case_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(call: EngineCall) -> Any:
        raise RuntimeError("nope")

    monkeypatch.setattr(runner, "ENGINE", boom)
    assert (
        main(
            [
                "--fake-llm",
                "--cases",
                "go-clean",
                "--sandbox",
                "local",
                "--no-readme",
                "--reports-dir",
                str(tmp_path),
                "--env-file",
                str(tmp_path / "none.env"),
            ]
        )
        == 1
    )


def test_cli_configuration_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_REVIEW_API_KEY", "")
    monkeypatch.setenv("LLM_CHEAP_API_KEY", "")
    none = str(tmp_path / "none.env")
    assert main(["--cases", "py-sql-injection", "--env-file", none, "--reports-dir", str(tmp_path)]) == 2
    assert main(["--fake-llm", "--cases", "nope", "--env-file", none, "--reports-dir", str(tmp_path)]) == 2
    assert main(["--fake-llm", "--ablations", "nope", "--env-file", none, "--reports-dir", str(tmp_path)]) == 2
    assert not list(tmp_path.glob("*.md"))
