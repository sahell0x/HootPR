"""Learnings: team preferences taught in chat or the dashboard (spec §8, phase-3 R11)."""

from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Learning(IdMixin, TimestampMixin, Base):
    """A team preference taught in chat or the dashboard (spec §8, phase-3 R11)."""

    __tablename__ = "learnings"
    __table_args__ = (Index("ix_learnings_org_repo", "org_id", "repo_id"),)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    repo_id: Mapped[UUID | None] = mapped_column(ForeignKey("repositories.id", ondelete="SET NULL"))
    # repo | org
    scope: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    path_glob: Mapped[str | None] = mapped_column(String(512))
    # Unconstrained dimensions: the embed model is an .env choice (R11).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    created_by_username: Mapped[str] = mapped_column(String(255))
    chat_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
