"""In-process KnowledgeBase for evals and tests (plan contract C2)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.knowledge.base import LearningHit, cosine, rank_hits
from app.llm.types import TraceContext


@dataclass(frozen=True)
class NewLearning:
    text: str
    scope: Literal["repo", "org"] = "repo"
    path_glob: str | None = None


class InMemoryKnowledge:
    """Learnings held in memory; entries are embedded once, on first use (ids ``L1``, ``L2``…)."""

    def __init__(
        self,
        entries: Sequence[NewLearning | str],
        embed: Callable[[list[str]], list[list[float]]],
        *,
        min_similarity: float = 0.25,
    ) -> None:
        self._entries = [e if isinstance(e, NewLearning) else NewLearning(e) for e in entries]
        self._embed = embed
        self._min = min_similarity
        self._vectors: list[list[float]] | None = None

    def learnings_for(
        self, query: str, paths: Sequence[str], *, k: int, trace: TraceContext
    ) -> list[LearningHit]:
        if not self._entries:
            return []
        if self._vectors is None:
            self._vectors = self._embed([e.text for e in self._entries])
        [q] = self._embed([query])
        hits = [
            LearningHit(f"L{i}", e.text, e.scope, e.path_glob, cosine(q, v))
            for i, (e, v) in enumerate(zip(self._entries, self._vectors, strict=True), 1)
        ]
        return rank_hits(hits, paths, k=k, min_similarity=self._min)
