from app.knowledge.memory import InMemoryKnowledge, NewLearning
from app.llm.types import TraceContext
from tests.fakes.keyword_embed import keyword_embed

T = TraceContext()


def test_in_memory_knowledge_returns_relevant_learnings() -> None:
    kb = InMemoryKnowledge(
        [
            "We use print for CLI output; do not flag print.",
            NewLearning("All SQL must be parameterized.", scope="org", path_glob="db/**"),
        ],
        keyword_embed,
    )
    hits = kb.learnings_for("task touching print statements in cli.py", ["cli.py"], k=8, trace=T)
    assert [h.id for h in hits] == ["L1"]
    sql = kb.learnings_for("review sql in db/users.py", ["db/users.py"], k=8, trace=T)
    assert [(h.id, h.scope, h.path_glob) for h in sql] == [("L2", "org", "db/**")]


def test_in_memory_knowledge_embeds_entries_once() -> None:
    calls: list[int] = []

    def embed(texts: list[str]) -> list[list[float]]:
        calls.append(len(texts))
        return keyword_embed(texts)

    kb = InMemoryKnowledge(["print rule"], embed)
    kb.learnings_for("print", [], k=3, trace=T)
    kb.learnings_for("print", [], k=3, trace=T)
    assert calls == [1, 1, 1]  # entries once, then one query embedding per call


def test_empty_knowledge_never_embeds() -> None:
    def embed(texts: list[str]) -> list[list[float]]:
        raise AssertionError("must not embed")

    assert InMemoryKnowledge([], embed).learnings_for("x", [], k=3, trace=T) == []
