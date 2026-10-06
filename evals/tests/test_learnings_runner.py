"""Learnings suite (phase-3 E2): two-pass runner, metrics and report over an injected engine, plus
the full-engine run (real engine + InMemoryKnowledge + oracle) once backend package B2 has landed."""

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hootpr_evals import learnings as L
from hootpr_evals import runner
from hootpr_evals.case import load_learning_cases
from hootpr_evals.embed import hash_embed
from hootpr_evals.runner import RunOptions, oracle_llm_factory, oracle_matcher_factory


@dataclass
class FakeCand:
    path: str
    start_line: int | None
    end_line: int
    severity: str = "major"
    category: str = "bug"
    title: str = "t"
    body: str = "b"
    confidence: float = 0.9


@dataclass
class FakeOutcome:
    inline: list[FakeCand]
    additional: list[FakeCand] = field(default_factory=list)
    learnings_used: list[Any] = field(default_factory=list)


def fake_engine(call: runner.EngineCall) -> FakeOutcome:
    """Reports every issue except 'suppress' ones when knowledge is present (and 'require' only then)."""
    has = call.knowledge is not None
    out = []
    for i in call.case.issues:
        if (i.learning_effect == "suppress" and has) or (i.learning_effect == "require" and not has):
            continue
        out.append(FakeCand(i.path, i.line_range[0], i.line_range[1], i.severity, i.category))
    return FakeOutcome(out, learnings_used=[object()] if has else [])


def ignoring_engine(call: runner.EngineCall) -> FakeOutcome:
    """A reviewer that ignores learnings: same findings in both passes, nothing retrieved."""
    return FakeOutcome(
        [FakeCand(i.path, i.line_range[0], i.line_range[1]) for i in call.case.issues if i.learning_effect != "require"]
    )


def test_two_pass_runner_and_metrics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, settings: Any) -> None:
    monkeypatch.setattr(runner, "ENGINE", fake_engine)
    cases = load_learning_cases()
    opts = RunOptions(settings=settings, sandbox="local", llm_match=False)
    results = [
        L.run_learning_case(c, opts, oracle_llm_factory(settings), oracle_matcher_factory(), tmp_path / c.id,
                            lambda llm: hash_embed)
        for c in cases
    ]  # fmt: skip
    m = L.learning_metrics(results)
    assert m.suppression_rate == 1.0 and m.adoption_rate == 1.0 and m.retention == 1.0
    assert m.retrieval_hit_rate == 1.0 and m.cases == 4 and m.findings_delta == -2
    assert all(r.learnings_total == 1 and r.learnings_used == 1 for r in results)
    assert all(r.baseline.error is None and r.with_learnings.error is None for r in results)


def test_metrics_of_a_reviewer_that_ignores_learnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, settings: Any
) -> None:
    monkeypatch.setattr(runner, "ENGINE", ignoring_engine)
    opts = RunOptions(settings=settings, llm_match=False)
    results = [
        L.run_learning_case(c, opts, oracle_llm_factory(settings), oracle_matcher_factory(), tmp_path / c.id,
                            lambda llm: hash_embed)
        for c in load_learning_cases()
    ]  # fmt: skip
    m = L.learning_metrics(results)
    assert m.suppression_rate == 0.0 and m.adoption_rate == 0.0 and m.retention == 1.0
    assert m.retrieval_hit_rate == 0.0 and m.findings_delta == 0


def test_metrics_are_none_without_a_denominator() -> None:
    m = L.learning_metrics([])
    assert (m.suppression_rate, m.adoption_rate, m.retention, m.retrieval_hit_rate, m.cases) == (
        None, None, None, 0.0, 0,
    )  # fmt: skip


def test_knowledge_is_built_from_the_case_learnings(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = pytest.importorskip("app.knowledge.memory")
    [case] = load_learning_cases(only=["py-print-cli"])
    kb = L.make_knowledge(case, hash_embed, min_similarity=0.0)
    assert isinstance(kb, memory.InMemoryKnowledge)
    from app.llm.types import TraceContext

    hits = kb.learnings_for("print statements in cli/main.py", ["cli/main.py"], k=8, trace=TraceContext())
    assert [h.id for h in hits] == ["L1"] and hits[0].path_glob == "cli/**"


def test_report_contains_the_learnings_table(tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from hootpr_evals.report import (
        render_learnings_markdown,
        update_learnings_readme,
        write_learnings_report,
    )

    monkeypatch.setattr(runner, "ENGINE", fake_engine)
    [case] = load_learning_cases(only=["py-print-cli"])
    r = L.run_learning_case(case, RunOptions(settings=settings, llm_match=False), oracle_llm_factory(settings),
                            oracle_matcher_factory(), tmp_path, lambda llm: hash_embed)  # fmt: skip
    metrics = L.learning_metrics([r])
    meta = {"model": "fake", "date": "2026-09-29", "fake_llm": "yes"}
    md = render_learnings_markdown(metrics, [r], meta)
    assert "| Suppression rate |" in md and "py-print-cli" in md
    assert "| Adoption rate | n/a |" in md and "| Findings delta | -1 |" in md
    md_path, js_path = write_learnings_report(metrics, [r], meta, tmp_path / "reports")
    assert md_path.name == "2026-09-29-fake-fake-learnings.md" and md_path.read_text() == md
    body = json.loads(js_path.read_text())
    assert body["metrics"]["suppression_rate"] == 1.0 and body["cases"][0]["case_id"] == "py-print-cli"
    readme = tmp_path / "README.md"
    readme.write_text("# evals\n\n<!-- learnings:start -->\nold\n<!-- learnings:end -->\n\n## After\n")
    update_learnings_readme(readme, metrics, md_path, meta)
    update_learnings_readme(readme, metrics, md_path, meta)  # idempotent
    text = readme.read_text()
    assert "old" not in text and text.count("| Suppression rate |") == 1 and "## After" in text
    assert f"(reports/{md_path.name})" in text


def test_full_engine_learnings_suite_with_fake_llm(tmp_path: Path, settings: Any) -> None:
    """Final verification: real engine + InMemoryKnowledge + oracle. Must not be skipped then."""
    pytest.importorskip("app.knowledge.memory")
    engine = pytest.importorskip("app.review.engine")
    if "knowledge" not in {f.name for f in dataclasses.fields(engine.EngineDeps)}:
        pytest.skip("EngineDeps.knowledge (contract C2, backend Task B9) not merged yet")
    cases = load_learning_cases()
    opts = RunOptions(settings=settings, sandbox="local", llm_match=False)
    results = [
        L.run_learning_case(c, opts, oracle_llm_factory(settings), oracle_matcher_factory(), tmp_path / c.id,
                            L.hash_embed_factory())
        for c in cases
    ]  # fmt: skip
    assert [(r.baseline.error, r.with_learnings.error) for r in results] == [(None, None)] * 4
    m = L.learning_metrics(results)
    assert m.retrieval_hit_rate == 1.0, [r.learnings_used for r in results]
    assert m.suppression_rate == 1.0 and m.adoption_rate == 1.0 and m.retention == 1.0


def test_seeded_knowledge_fallback_ranks_by_cosine() -> None:
    [case] = load_learning_cases(only=["py-print-cli"])
    kb = L.SeededKnowledge(case, hash_embed, min_similarity=0.0)
    [hit] = kb.learnings_for("never flag print statements in cli", ["cli/main.py"], k=8, trace=None)
    assert hit.id == "L1" and hit.path_glob == "cli/**" and hit.similarity > 0.5
    strict = L.SeededKnowledge(case, hash_embed, min_similarity=0.99)
    assert strict.learnings_for("golang rows", [], k=8, trace=None) == []
    assert kb.learnings_for("x", [], k=0, trace=None) == []


def test_errored_passes_are_excluded_from_the_rates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, settings: Any
) -> None:
    def broken_with_knowledge(call: runner.EngineCall) -> FakeOutcome:
        if call.knowledge is not None:
            raise TypeError("EngineDeps.__init__() got an unexpected keyword argument 'knowledge'")
        return fake_engine(call)

    monkeypatch.setattr(runner, "ENGINE", broken_with_knowledge)
    [case] = load_learning_cases(only=["py-print-cli"])
    r = L.run_learning_case(case, RunOptions(settings=settings, llm_match=False), oracle_llm_factory(settings),
                            oracle_matcher_factory(), tmp_path, lambda llm: hash_embed)  # fmt: skip
    assert r.with_learnings.error and "knowledge" in r.with_learnings.error
    m = L.learning_metrics([r])
    assert (m.suppression_rate, m.retention, m.retrieval_hit_rate, m.findings_delta) == (None, None, 0.0, 0)
    assert (m.errors, m.cases) == (1, 1)
