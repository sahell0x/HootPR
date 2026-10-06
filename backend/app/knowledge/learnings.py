"""Learnings in Postgres + pgvector (spec §8, phase-3 R11-R15).

Only rows embedded with the current ``LLM_EMBED_MODEL`` are compared (R11); rows without an
embedding (provider down when they were added, or a model change) are picked up by
``learnings.embed`` / the hourly ``maintenance.embed_missing_learnings`` beat.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from app.knowledge.base import Embedder, LearningHit, rank_hits
from app.knowledge.text import clean_learning_text
from app.llm.types import TraceContext
from app.logging import get_logger
from app.models import Learning, Repository
from app.settings import Settings

log = get_logger(__name__)
ScopeMode = Literal["local", "global"]
QUERY_MAX_CHARS = 8000
# Nearest-neighbour candidates fetched per query, before thresholding + path boost.
CANDIDATE_FACTOR = 3
# embed_missing's one-by-one fallback gives up after this many consecutive failures.
FALLBACK_MAX_MISSES = 3


def effective_scope(setting: Literal["local", "global", "auto"], private: bool) -> ScopeMode:
    """``auto`` = global (whole org) for private repositories, local for public ones (§9)."""
    if setting == "auto":
        return "global" if private else "local"
    return setting


@dataclass(frozen=True)
class AddedLearning:
    id: str
    text: str
    scope: str
    path_glob: str | None


class SqlKnowledge:
    """``KnowledgeBase`` over the ``learnings`` table for one org (+ repo in local mode)."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedder: Embedder,
        settings: Settings,
        *,
        org_id: UUID,
        repo_id: UUID | None,
        mode: ScopeMode,
    ) -> None:
        self._sf, self._emb, self._s = session_factory, embedder, settings
        self._org, self._repo, self._mode = org_id, repo_id, mode

    def bind_embedder(self, embedder: Embedder) -> SqlKnowledge:
        """The same store embedding through ``embedder`` (a ``MeteredLLM``: usage/cost counted
        in the review's or chat's totals)."""
        return SqlKnowledge(
            self._sf,
            embedder,
            self._s,
            org_id=self._org,
            repo_id=self._repo,
            mode=self._mode,
        )

    def learnings_for(
        self, query: str, paths: Sequence[str], *, k: int, trace: TraceContext
    ) -> list[LearningHit]:
        if not query.strip() or k <= 0:
            return []
        with self._sf() as s:
            exists = select(Learning.id).where(*self._filters()).limit(1)
            if s.execute(exists).first() is None:
                return []  # nothing to compare against: skip the embedding call
        [q] = self._emb.embed([query[:QUERY_MAX_CHARS]], trace)
        dist = Learning.embedding.cosine_distance(q)
        stmt = (
            select(Learning, dist.label("d"))
            .where(*self._filters(), func.vector_dims(Learning.embedding) == len(q))
            .order_by(dist)
            .limit(k * CANDIDATE_FACTOR)
        )
        with self._sf() as s:
            rows = s.execute(stmt).all()
        hits = [
            LearningHit(
                str(r.id),
                r.text,
                "org" if r.scope == "org" else "repo",
                r.path_glob,
                1.0 - float(d),
                r.source_url,
            )
            for r, d in rows
        ]
        return rank_hits(hits, paths, k=k, min_similarity=self._s.learnings_min_similarity)

    def _filters(self) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = [
            Learning.org_id == self._org,
            Learning.embedding.is_not(None),
            Learning.embedding_model == self._s.llm_embed_model,
        ]
        if self._mode == "local":
            # Local (``auto`` on public repositories): this repository's learnings plus
            # org-wide ones that are not private knowledge — created in the dashboard or
            # taught in a public repository. Org learnings from private repos never leak here.
            public_repos = select(Repository.id).where(
                Repository.org_id == self._org, Repository.private.is_(False)
            )
            org_public = and_(
                Learning.scope == "org",
                or_(Learning.repo_id.is_(None), Learning.repo_id.in_(public_repos)),
            )
            conds.append(or_(Learning.repo_id == self._repo, org_public))
        return conds


def _embed(embedder: Embedder, texts: list[str], trace: TraceContext) -> list[list[float]] | None:
    try:
        vecs = embedder.embed(texts, trace)
    except Exception:
        log.warning("learning_embed_failed", n=len(texts), exc_info=True)
        return None
    return vecs if len(vecs) == len(texts) else None


def add_learning(
    s: Session,
    embedder: Embedder,
    settings: Settings,
    *,
    org_id: UUID,
    repo_id: UUID | None,
    text: str,
    scope: Literal["repo", "org"],
    path_glob: str | None,
    source_url: str | None,
    pr_number: int | None,
    author: str,
    chat_message_id: UUID | None,
    trace: TraceContext,
) -> AddedLearning:
    """Validate, redact, embed (best effort) and insert; the caller commits.

    Raises ``InvalidLearning`` for empty/too long/injection-looking text (R14)."""
    clean = clean_learning_text(text)
    vecs = _embed(embedder, [clean], trace)
    vec = vecs[0] if vecs else None
    glob = (path_glob or "").strip()[:512] or None
    row = Learning(
        org_id=org_id,
        repo_id=repo_id,
        scope=scope,
        text=clean,
        path_glob=glob,
        embedding=vec,
        embedding_model=settings.llm_embed_model if vec is not None else None,
        source_url=source_url,
        pr_number=pr_number,
        created_by_username=author,
        chat_message_id=chat_message_id,
    )
    s.add(row)
    s.flush()
    return AddedLearning(str(row.id), clean, scope, glob)


def embed_learning(
    session_factory: sessionmaker[Session],
    embedder: Embedder,
    settings: Settings,
    learning_id: UUID,
) -> bool:
    """(Re-)embed one learning; False when it is gone or the provider failed."""
    with session_factory() as s:
        row = s.get(Learning, learning_id)
        if row is None:
            return False
        trace = TraceContext(org_id=row.org_id, stage="learnings")
        vecs = _embed(embedder, [row.text], trace)
        if not vecs:
            return False
        row.embedding, row.embedding_model = vecs[0], settings.llm_embed_model
        s.commit()
        return True


def embed_missing(
    session_factory: sessionmaker[Session],
    embedder: Embedder,
    settings: Settings,
    *,
    limit: int = 100,
) -> int:
    """Embed up to ``limit`` rows without a current-model embedding: one batch per org (the
    spend is attributed to that org); a failed batch falls back to one call per row so a row the
    provider rejects never blocks the others."""
    with session_factory() as s:
        rows = list(
            s.execute(
                select(Learning)
                .where(
                    or_(
                        Learning.embedding.is_(None),
                        Learning.embedding_model.is_(None),
                        Learning.embedding_model != settings.llm_embed_model,
                    )
                )
                .order_by(Learning.created_at)
                .limit(limit)
            ).scalars()
        )
        by_org: dict[UUID, list[Learning]] = {}
        for r in rows:
            by_org.setdefault(r.org_id, []).append(r)
        done = 0
        for org_id, batch in by_org.items():
            trace = TraceContext(org_id=org_id, stage="learnings")
            vecs = _embed(embedder, [r.text for r in batch], trace)
            if vecs is not None:
                pairs = list(zip(batch, vecs, strict=True))
            else:
                pairs = []
                misses = 0
                for r in batch if len(batch) > 1 else []:
                    if misses >= FALLBACK_MAX_MISSES:
                        break  # the provider is down, not one bad row: retry next hour
                    one = _embed(embedder, [r.text], trace)
                    if one is None:
                        misses += 1
                        log.warning("learning_embed_skipped", learning_id=str(r.id))
                        continue
                    misses = 0
                    pairs.append((r, one[0]))
            for r, v in pairs:
                r.embedding, r.embedding_model = v, settings.llm_embed_model
            done += len(pairs)
        s.commit()
        return done


def purge_learnings(s: Session, org_id: UUID, repo_id: UUID | None = None) -> int:
    """Delete an org's learnings, or one repository's repo-scoped ones; the caller commits
    (opt-out, R15). Org-scoped rows taught in the repository apply org-wide and are kept."""
    stmt = delete(Learning).where(Learning.org_id == org_id)
    if repo_id is not None:
        stmt = stmt.where(Learning.repo_id == repo_id, Learning.scope == "repo")
    res = cast(CursorResult[tuple[()]], s.execute(stmt))
    return int(res.rowcount or 0)
