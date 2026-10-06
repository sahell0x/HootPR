"""Learnings eval suite (phase-3 E2): does a learning taught in chat measurably change the next review?

Every learning case is reviewed twice by the same engine: once without knowledge (baseline) and once
with an in-memory knowledge base seeded from the case's `learnings.yaml` (contract C2
`InMemoryKnowledge`). Expected issues carry a `learning_effect`:

- `suppress` — should be reported without the learning and dropped with it (suppression rate);
- `require`  — should only be reported once the learning is known (adoption rate);
- `none`     — must survive either way (retention = recall with ÷ recall without).

Retrieval hit rate is the share of cases whose second pass actually injected a learning."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.llm.types import TraceContext
from app.settings import Settings

from hootpr_evals.case import Case
from hootpr_evals.embed import hash_embed
from hootpr_evals.metrics import CaseResult
from hootpr_evals.runner import LLMFactory, MatcherFactory, RunOptions, run_case

EmbedFn = Callable[[list[str]], list[list[float]]]
EmbedFactory = Callable[[Any], EmbedFn]  # LLMGateway -> embed function


@dataclass(frozen=True)
class LearningCaseResult:
    case_id: str
    baseline: CaseResult
    with_learnings: CaseResult
    learnings_used: int
    learnings_total: int


@dataclass(frozen=True)
class LearningMetrics:
    suppression_rate: float | None
    adoption_rate: float | None
    retention: float | None
    retrieval_hit_rate: float
    findings_delta: int
    cases: int
    errors: int = 0  # cases where either pass raised


@dataclass(frozen=True)
class SeededHit:
    """Shape of contract C2 `LearningHit` (fallback only)."""

    id: str
    text: str
    scope: str
    path_glob: str | None
    similarity: float
    source_url: str | None = None


class SeededKnowledge:
    """Fallback C2 `KnowledgeBase` used only when the backend's `app.knowledge.memory` is not
    importable (runner tests over an injected engine). Cosine ranking, no path boost; the real
    engine run always uses the production `InMemoryKnowledge`."""

    def __init__(self, case: Case, embed: EmbedFn, *, min_similarity: float) -> None:
        self.entries = case.learnings
        self._embed, self._min = embed, min_similarity
        self._vectors: list[list[float]] | None = None

    def learnings_for(self, query: str, paths: Sequence[str], *, k: int, trace: Any) -> list[SeededHit]:
        if not self.entries or k <= 0:
            return []
        if self._vectors is None:
            self._vectors = self._embed([e.text for e in self.entries])
        [q] = self._embed([query])
        scored = [(sum(x * y for x, y in zip(q, v, strict=True)), i) for i, v in enumerate(self._vectors)]
        hits = [
            SeededHit(f"L{i + 1}", self.entries[i].text, self.entries[i].scope, self.entries[i].path_glob, sim)
            for sim, i in sorted(scored, key=lambda t: (-t[0], t[1]))
            if sim >= self._min
        ]
        return hits[:k]


def make_knowledge(case: Case, embed: EmbedFn, *, min_similarity: float) -> Any:
    """An `InMemoryKnowledge` over the case's learnings (backend imported lazily: contract C2), or a
    `SeededKnowledge` stand-in while the backend knowledge package is not available."""
    try:
        from app.knowledge.memory import (  # type: ignore[import-not-found,unused-ignore]
            InMemoryKnowledge,
            NewLearning,
        )
    except ImportError:
        return SeededKnowledge(case, embed, min_similarity=min_similarity)
    entries = [NewLearning(text=e.text, scope=e.scope, path_glob=e.path_glob) for e in case.learnings]
    return InMemoryKnowledge(entries, embed, min_similarity=min_similarity)


def run_learning_case(
    case: Case,
    opts: RunOptions,
    llm_factory: LLMFactory,
    matcher_factory: MatcherFactory,
    workdir: Path,
    embed_factory: EmbedFactory,
    *,
    min_similarity: float = 0.0,
) -> LearningCaseResult:
    """Baseline pass without knowledge, then a pass with the case's learnings. The case is
    materialized identically (fixed identity and dates) for both passes."""
    baseline = run_case(case, opts, llm_factory, matcher_factory, workdir / "baseline")
    with_learnings = run_case(
        case,
        opts,
        llm_factory,
        matcher_factory,
        workdir / "with-learnings",
        knowledge_factory=lambda llm: make_knowledge(case, embed_factory(llm), min_similarity=min_similarity),
    )
    return LearningCaseResult(case.id, baseline, with_learnings, with_learnings.learnings_used, len(case.learnings))


def _matched_ids(r: CaseResult) -> set[str]:
    return {iid for _, iid in r.match.matched}


def learning_metrics(results: Sequence[LearningCaseResult]) -> LearningMetrics:
    """Rates, hit rate and delta are computed over the cases where both passes completed; a pass
    that raised would otherwise read as a perfectly suppressed issue. Errors are counted apart."""
    ok = [r for r in results if not (r.baseline.error or r.with_learnings.error)]
    suppressed = suppress_base = adopted = require_missing = 0
    none_total = none_without = none_with = 0
    for r in ok:
        before, after = _matched_ids(r.baseline), _matched_ids(r.with_learnings)
        for issue in r.baseline.expected:
            if issue.learning_effect == "suppress" and issue.id in before:
                suppress_base += 1
                suppressed += issue.id not in after
            elif issue.learning_effect == "require" and issue.id not in before:
                require_missing += 1
                adopted += issue.id in after
            elif issue.learning_effect == "none":
                none_total += 1
                none_without += issue.id in before
                none_with += issue.id in after
    return LearningMetrics(
        suppression_rate=suppressed / suppress_base if suppress_base else None,
        adoption_rate=adopted / require_missing if require_missing else None,
        # recall with ÷ recall without over the same issue set = matched with ÷ matched without
        retention=none_with / none_without if none_total and none_without else None,
        retrieval_hit_rate=sum(1 for r in ok if r.learnings_used > 0) / len(ok) if ok else 0.0,
        findings_delta=sum(len(r.with_learnings.findings) - len(r.baseline.findings) for r in ok),
        cases=len(results),
        errors=len(results) - len(ok),
    )


def real_embed_factory(settings: Settings) -> EmbedFactory:
    """Embeddings through the case's gateway (`embed` role, `LLM_EMBED_MODEL`), as in production."""
    del settings  # the gateway already carries the embed role config built from these settings

    def factory(llm: Any) -> EmbedFn:
        def embed(texts: list[str]) -> list[list[float]]:
            vectors: list[list[float]] = llm.embed(texts, TraceContext())
            return vectors

        return embed

    return factory


def hash_embed_factory() -> EmbedFactory:
    """Deterministic hashing embedder for fake-LLM runs (no gateway call)."""
    return lambda llm: hash_embed
