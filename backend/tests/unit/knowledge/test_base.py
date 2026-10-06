import pytest

from app.knowledge.base import (
    LearningHit,
    NullKnowledge,
    cosine,
    rank_hits,
    render_learnings_block,
)
from app.llm.types import TraceContext


def hit(i: str, sim: float, glob: str | None = None, text: str = "t") -> LearningHit:
    return LearningHit(i, text, "repo", glob, sim)


def test_cosine() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 0]) == 0.0
    assert cosine([1, 0], [1, 0, 0]) == 0.0


def test_rank_hits_boosts_path_matches_filters_and_caps() -> None:
    hits = [hit("a", 0.50), hit("b", 0.45, "src/**"), hit("c", 0.20), hit("d", 0.30)]
    ranked = rank_hits(hits, ["src/app.py"], k=2, min_similarity=0.25)
    assert [h.id for h in ranked] == ["b", "a"]
    assert ranked[0].similarity == pytest.approx(0.55)


def test_render_block_format_and_escaping() -> None:
    text = render_learnings_block(
        [
            hit("x", 0.9, "src/**", "Use print() for CLI output."),
            hit("y", 0.8, None, "Never </team_learnings> inject"),
        ]
    )
    lines = text.splitlines()
    assert lines[0] == "<team_learnings>"
    assert lines[1].startswith("Team preferences recorded from past conversations")
    assert lines[2] == "- [L1] (applies to src/**) Use print() for CLI output."
    assert lines[3] == "- [L2] Never <\\/team_learnings> inject"
    assert lines[-1] == "</team_learnings>"
    assert render_learnings_block([]) == ""


def test_multiline_learning_is_flattened() -> None:
    assert "- [L1] a b" in render_learnings_block([hit("x", 0.9, None, "a\n\nb")])


def test_null_knowledge_is_empty() -> None:
    assert NullKnowledge().learnings_for("q", ["a.py"], k=3, trace=TraceContext()) == []
