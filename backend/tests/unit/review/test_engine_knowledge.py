from pathlib import Path
from typing import Any

import pytest

from app.config.schema import HootPRConfig
from app.knowledge.memory import InMemoryKnowledge
from app.review.ast_grep import AstGrepMatch
from app.review.engine import run_engine
from app.settings import Settings
from tests.fakes.engine_llm import EngineFakeLLM
from tests.fakes.keyword_embed import keyword_embed
from tests.unit.review.test_engine import SQLI, harness

NIT: dict[str, Any] = {
    "path": "app/db.py",
    "start_line": None,
    "end_line": 2,
    "severity": "minor",
    "category": "style",
    "title": "Avoid print debugging",
    "confidence": 0.9,
}
LEARNING = "We use print for CLI output in db code; never flag print."


def titles(res: Any) -> set[str]:
    return {c.title for c in [*res.inline, *res.additional]}


def test_learning_is_injected_and_suppresses_matching_finding(
    tmp_path: Path, settings: Settings
) -> None:
    h = harness(tmp_path, settings)
    h.fake.findings = [SQLI, NIT]
    h.fake.suppress = {"Avoid print debugging": "print"}
    base = run_engine(h.inputs, h.deps)
    assert titles(base) == {"SQL injection", "Avoid print debugging"}
    assert base.learnings_used == []
    assert not any("<team_learnings>" in t for t in h.fake.user_texts["agent"])

    h2 = harness(tmp_path / "2", settings)
    h2.fake.findings = [SQLI, NIT]
    h2.fake.suppress = {"Avoid print debugging": "print"}
    h2.deps.knowledge = InMemoryKnowledge([LEARNING], keyword_embed, min_similarity=0.0)
    after = run_engine(h2.inputs, h2.deps)
    assert titles(after) == {"SQL injection"}
    assert [x.id for x in after.learnings_used] == ["L1"]
    assert any("<team_learnings>" in t for t in h2.fake.user_texts["agent"])
    assert any("<team_learnings>" in t for t in h2.fake.user_texts["JudgeBatch"])


def test_learning_reaches_single_pass_fallback(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings, fake=EngineFakeLLM(tools=False))
    h.fake.findings = [SQLI, NIT]
    h.fake.suppress = {"Avoid print debugging": "print"}
    h.deps.knowledge = InMemoryKnowledge([LEARNING], keyword_embed, min_similarity=0.0)
    res = run_engine(h.inputs, h.deps)
    assert titles(res) == {"SQL injection"}
    assert any("<team_learnings>" in t for t in h.fake.user_texts["SinglePassFindings"])


def test_knowledge_failure_degrades_but_review_continues(
    tmp_path: Path, settings: Settings
) -> None:
    class Broken:
        def learnings_for(self, *a: object, **k: object) -> list[object]:
            raise RuntimeError("embed down")

    h = harness(tmp_path, settings)
    h.fake.findings = [SQLI]
    h.deps.knowledge = Broken()  # type: ignore[assignment]
    res = run_engine(h.inputs, h.deps)
    assert res.degraded["learnings"] == "unavailable" and len(res.inline) == 1


def test_guidelines_from_base_reach_the_agent(tmp_path: Path, settings: Settings) -> None:
    h = harness(
        tmp_path,
        settings,
        base={
            "app/db.py": "def get(conn, uid):\n    return conn.execute('select 1')\n",
            "CLAUDE.md": "Always use parameterized queries.\n",
            "web/AGENTS.md": "Use React hooks.\n",
        },
    )
    h.fake.findings = [SQLI]
    res = run_engine(h.inputs, h.deps)
    assert res.guidelines_used == ["CLAUDE.md"]  # web/AGENTS.md applies to no reviewed file
    agent = h.fake.user_texts["agent"]
    assert any('<guidelines source="CLAUDE.md" scope="/">' in t for t in agent)
    assert not any("Use React hooks." in t for t in agent)
    assert "guideline" in next(s for s in h.sink.stages if s.name == "context").detail


def test_guidelines_disabled_by_opt_out(tmp_path: Path, settings: Settings) -> None:
    h = harness(
        tmp_path,
        settings,
        base={"app/db.py": "x = 1\n", "CLAUDE.md": "Always use parameterized queries.\n"},
        config=HootPRConfig.model_validate({"knowledge_base": {"opt_out": True}}),
    )
    h.fake.findings = [SQLI]
    res = run_engine(h.inputs, h.deps)
    assert res.guidelines_used == []
    assert not any("<guidelines" in t for t in h.fake.user_texts["agent"])


def test_ast_grep_matches_become_instructions(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.review.engine as eng

    seen: list[Any] = []

    def fake_run(*a: Any, **k: Any) -> tuple[list[AstGrepMatch], str | None]:
        seen.append(a)
        m = AstGrepMatch(
            "no-fstring-sql",
            "app/db.py",
            2,
            2,
            "Never build SQL with f-strings.",
            "error",
            "Never build SQL with f-strings.",
        )
        return [m], None

    monkeypatch.setattr(eng, "run_ast_grep", fake_run)
    h = harness(tmp_path, settings)
    h.fake.findings = [SQLI]
    run_engine(h.inputs, h.deps)
    assert any(
        "AST-grep instruction line 2 [no-fstring-sql]: Never build SQL with f-strings." in t
        for t in h.fake.user_texts["agent"]
    )
    _sb, _cfg, base_sha, changed, _s = seen[0]
    assert base_sha == h.inputs.pr.base_sha and changed == {"app/db.py": {2}}


def test_ast_grep_degradation_is_recorded(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.review.engine as eng

    monkeypatch.setattr(eng, "run_ast_grep", lambda *a, **k: ([], "ast-grep unavailable"))
    h = harness(tmp_path, settings)
    h.fake.findings = [SQLI]
    res = run_engine(h.inputs, h.deps)
    assert res.degraded["ast_grep"] == "ast-grep unavailable" and len(res.inline) == 1


def test_knowledge_embeddings_are_metered_in_the_review_totals(
    tmp_path: Path, settings: Settings
) -> None:
    from app.llm.types import TraceContext
    from app.review.llm import MeteredLLM

    bound: list[Any] = []

    class Bindable:
        def bind_embedder(self, embedder: Any) -> "Bindable":
            bound.append(embedder)
            return self

        def learnings_for(self, query: str, paths: Any, *, k: int, trace: TraceContext) -> list:
            bound[-1].embed([query], trace)
            return []

    h = harness(tmp_path, settings)
    h.fake.findings = [SQLI]
    h.deps.knowledge = Bindable()  # type: ignore[assignment]
    res = run_engine(h.inputs, h.deps)
    assert len(bound) == 1 and isinstance(bound[0], MeteredLLM)
    assert "model-embed" in bound[0].models and res.models == bound[0].models
