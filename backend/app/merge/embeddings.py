"""Issue and PR embeddings in pgvector: related PRs and duplicate issues (spec §10.2).

Scope follows ``knowledge_base.pull_requests.scope`` / ``knowledge_base.issues.scope`` (``auto``:
the whole org for private repositories, this repository for public ones). A public repository
never sees rows from private repositories. Only rows embedded with the current
``LLM_EMBED_MODEL`` (and the same dimensions) are compared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from uuid_utils.compat import uuid7

from app.knowledge.learnings import ScopeMode
from app.models import IssueEmbedding, PrEmbedding, Repository
from app.models.base import utcnow

TEXT_MAX_CHARS = 6000


@dataclass(frozen=True)
class Similar:
    number: int
    title: str
    url: str
    repo_full_name: str
    similarity: float
    state: str = "open"


def pr_text(title: str, summary: str) -> str:
    return f"{title}\n\n{summary}"[:TEXT_MAX_CHARS]


def issue_text(title: str, body: str) -> str:
    return f"{title}\n\n{body}"[:TEXT_MAX_CHARS]


def upsert_pr_embedding(
    s: Session,
    *,
    org_id: UUID,
    repo_id: UUID,
    pr_id: UUID,
    number: int,
    title: str,
    url: str,
    summary: str,
    vector: list[float],
    model: str,
) -> None:
    now = utcnow()
    values: dict[str, Any] = {
        "org_id": org_id,
        "repo_id": repo_id,
        "pr_number": number,
        "title": title[:512],
        "url": url[:1024],
        "summary": summary[:TEXT_MAX_CHARS],
        "embedding": vector,
        "embedding_model": model,
        "updated_at": now,
    }
    s.execute(
        insert(PrEmbedding)
        .values(id=uuid7(), created_at=now, pr_id=pr_id, **values)
        .on_conflict_do_update(index_elements=["pr_id"], set_=values)
    )


def upsert_issue_embedding(
    s: Session,
    *,
    org_id: UUID,
    repo_id: UUID,
    number: int,
    title: str,
    url: str,
    state: str,
    vector: list[float],
    model: str,
) -> None:
    now = utcnow()
    values: dict[str, Any] = {
        "org_id": org_id,
        "title": title[:512],
        "url": url[:1024],
        "state": state[:16],
        "embedding": vector,
        "embedding_model": model,
        "updated_at": now,
    }
    s.execute(
        insert(IssueEmbedding)
        .values(id=uuid7(), created_at=now, repo_id=repo_id, issue_number=number, **values)
        .on_conflict_do_update(index_elements=["repo_id", "issue_number"], set_=values)
    )


def _scope_filters(
    model: type[PrEmbedding] | type[IssueEmbedding],
    org_id: UUID,
    repo_id: UUID,
    mode: ScopeMode,
    private: bool,
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [model.org_id == org_id]
    if mode == "local":
        conds.append(model.repo_id == repo_id)
    elif not private:
        conds.append(Repository.private.is_(False))
    return conds


def related_prs(
    s: Session,
    *,
    org_id: UUID,
    repo_id: UUID,
    pr_id: UUID,
    vector: list[float],
    embed_model: str,
    mode: ScopeMode,
    private: bool,
    k: int,
    min_similarity: float,
) -> list[Similar]:
    dist = PrEmbedding.embedding.cosine_distance(vector)
    rows = s.execute(
        select(PrEmbedding, Repository.full_name, dist.label("d"))
        .join(Repository, Repository.id == PrEmbedding.repo_id)
        .where(
            *_scope_filters(PrEmbedding, org_id, repo_id, mode, private),
            PrEmbedding.pr_id != pr_id,
            PrEmbedding.embedding.is_not(None),
            PrEmbedding.embedding_model == embed_model,
            func.vector_dims(PrEmbedding.embedding) == len(vector),
        )
        .order_by(dist)
        .limit(k)
    ).all()
    return [
        Similar(r.pr_number, r.title, r.url, full, 1.0 - float(d))
        for r, full, d in rows
        if 1.0 - float(d) >= min_similarity
    ]


def similar_issues(
    s: Session,
    *,
    org_id: UUID,
    repo_id: UUID,
    exclude_number: int | None,
    vector: list[float],
    embed_model: str,
    mode: ScopeMode,
    private: bool,
    k: int,
    min_similarity: float,
) -> list[Similar]:
    dist = IssueEmbedding.embedding.cosine_distance(vector)
    conds = _scope_filters(IssueEmbedding, org_id, repo_id, mode, private)
    if exclude_number is not None:
        conds.append(
            ~((IssueEmbedding.repo_id == repo_id) & (IssueEmbedding.issue_number == exclude_number))
        )
    rows = s.execute(
        select(IssueEmbedding, Repository.full_name, dist.label("d"))
        .join(Repository, Repository.id == IssueEmbedding.repo_id)
        .where(
            *conds,
            IssueEmbedding.embedding.is_not(None),
            IssueEmbedding.embedding_model == embed_model,
            func.vector_dims(IssueEmbedding.embedding) == len(vector),
        )
        .order_by(dist)
        .limit(k)
    ).all()
    return [
        Similar(r.issue_number, r.title, r.url, full, 1.0 - float(d), r.state)
        for r, full, d in rows
        if 1.0 - float(d) >= min_similarity
    ]


def purge_embeddings(s: Session, org_id: UUID, repo_id: UUID | None = None) -> int:
    """Knowledge-base opt-out: delete the org's (or one repository's) issue + PR embeddings."""
    n = 0
    for model in (PrEmbedding, IssueEmbedding):
        stmt = delete(model).where(model.org_id == org_id)
        if repo_id is not None:
            stmt = stmt.where(model.repo_id == repo_id)
        res = s.execute(stmt)
        n += int(res.rowcount) if isinstance(res, CursorResult) else 0
    return n
