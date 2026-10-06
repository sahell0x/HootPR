"""Learnings dashboard API (plan contract C1, spec §8).

Members read; admins create, edit and delete. Every create or text edit clears the stored
embedding and queues ``learnings.embed`` (plan contract C6).
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas as S
from app.deps import Db, OrgAdmin, OrgContext, OrgMember, get_queue
from app.errors import api_error
from app.knowledge.text import InvalidLearning, clean_learning_text
from app.models import Identity, Learning, Repository

router = APIRouter()
EMBED_TASK = "learnings.embed"


def _out(row: Learning, repo_name: str | None) -> S.Learning:
    return S.Learning(
        id=str(row.id),
        text=row.text,
        scope="repo" if row.scope == "repo" else "org",
        repo_id=str(row.repo_id) if row.repo_id else None,
        repo_full_name=repo_name,
        path_glob=row.path_glob,
        source_url=row.source_url,
        pr_number=row.pr_number,
        created_by_username=row.created_by_username,
        embedded=row.embedding is not None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _repo_name(db: AsyncSession, repo_id: UUID | None) -> str | None:
    if repo_id is None:
        return None
    stmt = select(Repository.full_name).where(Repository.id == repo_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _own(db: AsyncSession, ctx: OrgContext, learning_id: UUID) -> Learning:
    stmt = select(Learning).where(Learning.id == learning_id, Learning.org_id == ctx.org.id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise api_error(404, "not_found", "Learning not found")
    return row


async def _org_repo_id(db: AsyncSession, ctx: OrgContext, raw: str | None) -> UUID | None:
    """``raw`` as the id of a repository in this org; None when absent or not found."""
    if not raw:
        return None
    try:
        repo_id = UUID(raw)
    except ValueError:
        return None
    stmt = select(Repository.id).where(Repository.id == repo_id, Repository.org_id == ctx.org.id)
    return (await db.execute(stmt)).scalar_one_or_none()


def _clean(text: str) -> str:
    try:
        return clean_learning_text(text)
    except InvalidLearning as exc:
        raise api_error(422, "invalid_learning", str(exc)) from exc


def _glob(value: str | None) -> str | None:
    return (value or "").strip() or None


async def _username(db: AsyncSession, ctx: OrgContext) -> str:
    """The user's username on the org's provider, falling back to their display name."""
    stmt = (
        select(Identity.username)
        .where(Identity.user_id == ctx.user.id, Identity.provider == ctx.org.provider)
        .order_by(Identity.created_at)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() or ctx.user.display_name


@router.get("/api/orgs/{org_slug}/learnings", response_model=S.LearningList)
async def list_learnings(
    ctx: OrgMember,
    db: Db,
    repo_id: UUID | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    before: datetime | None = None,
) -> S.LearningList:
    stmt = (
        select(Learning, Repository.full_name)
        .outerjoin(Repository, Repository.id == Learning.repo_id)
        .where(Learning.org_id == ctx.org.id)
    )
    if repo_id is not None:
        stmt = stmt.where(Learning.repo_id == repo_id)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Learning.text.ilike(f"%{escaped}%", escape="\\"))
    if before is not None:
        stmt = stmt.where(Learning.created_at < before)
    stmt = stmt.order_by(Learning.created_at.desc(), Learning.id.desc()).limit(limit + 1)
    rows = [(row, name) for row, name in (await db.execute(stmt)).all()]
    more = len(rows) > limit
    rows = rows[:limit]
    return S.LearningList(
        learnings=[_out(row, name) for row, name in rows],
        next_before=rows[-1][0].created_at.isoformat() if more and rows else None,
    )


@router.post("/api/orgs/{org_slug}/learnings", response_model=S.Learning, status_code=201)
async def create_learning(
    body: S.LearningCreate, ctx: OrgAdmin, db: Db, request: Request
) -> S.Learning:
    if ctx.org.knowledge_base_opt_out:
        raise api_error(
            409,
            "knowledge_base_opted_out",
            "This organization opted out of the knowledge base; learnings are not stored.",
        )
    text = _clean(body.text)
    repo_id = await _org_repo_id(db, ctx, body.repo_id)
    if body.repo_id and repo_id is None:
        raise api_error(422, "invalid_scope", "Repository not found in this organization")
    if body.scope == "repo" and repo_id is None:
        raise api_error(422, "invalid_scope", "A repository learning needs a repo_id")
    row = Learning(
        org_id=ctx.org.id,
        repo_id=repo_id,
        scope=body.scope,
        text=text,
        path_glob=_glob(body.path_glob),
        created_by_username=await _username(db, ctx),
    )
    db.add(row)
    await db.flush()
    await db.commit()
    await db.refresh(row)
    get_queue(request).enqueue(EMBED_TASK, str(row.id))
    return _out(row, await _repo_name(db, row.repo_id))


@router.patch("/api/orgs/{org_slug}/learnings/{learning_id}", response_model=S.Learning)
async def update_learning(
    learning_id: UUID, body: S.LearningUpdate, ctx: OrgAdmin, db: Db, request: Request
) -> S.Learning:
    row = await _own(db, ctx, learning_id)
    reembed = False
    if body.text is not None:
        text = _clean(body.text)
        if text != row.text:
            row.text, row.embedding, row.embedding_model = text, None, None
            reembed = True
    if body.scope is not None:
        if body.scope == "repo" and row.repo_id is None:
            raise api_error(
                422, "invalid_scope", "Only a learning taught in a repository can be repo-scoped"
            )
        row.scope = body.scope
    if "path_glob" in body.model_fields_set:
        row.path_glob = _glob(body.path_glob)
    await db.commit()
    await db.refresh(row)
    if reembed:
        get_queue(request).enqueue(EMBED_TASK, str(row.id))
    return _out(row, await _repo_name(db, row.repo_id))


@router.delete("/api/orgs/{org_slug}/learnings/{learning_id}", status_code=204)
async def delete_learning(learning_id: UUID, ctx: OrgAdmin, db: Db) -> Response:
    row = await _own(db, ctx, learning_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
