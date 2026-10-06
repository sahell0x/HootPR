"""Phase 5: pre-merge check results, linked issues, issue/PR embeddings (spec §10.2)."""

from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class PreMergeResult(IdMixin, TimestampMixin, Base):
    """One pre-merge check outcome for one reviewed head SHA."""

    __tablename__ = "pre_merge_results"
    __table_args__ = (Index("ix_pre_merge_results_pr_sha", "pr_id", "head_sha"),)
    pr_id: Mapped[UUID] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"))
    review_id: Mapped[UUID | None] = mapped_column(ForeignKey("reviews.id", ondelete="SET NULL"))
    head_sha: Mapped[str] = mapped_column(String(64))
    # title | description | docstrings | issue_assessment | custom
    kind: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(8))  # warning | error
    status: Mapped[str] = mapped_column(String(16))  # passed | failed | inconclusive
    explanation: Mapped[str] = mapped_column(Text, default="")
    ignored: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ignored_by: Mapped[str | None] = mapped_column(String(255))


class IssueLink(IdMixin, TimestampMixin, Base):
    """An issue a PR references (closing keyword or URL) and HootPR's assessment of it."""

    __tablename__ = "issue_links"
    __table_args__ = (UniqueConstraint("pr_id", "issue_repo", "issue_number"),)
    pr_id: Mapped[UUID] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"))
    issue_repo: Mapped[str] = mapped_column(String(512))  # owner/name or group/.../project
    issue_number: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(1024), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    # addressed | partially | not_addressed | unclear | unavailable
    assessment: Mapped[str] = mapped_column(String(16), default="unclear")
    explanation: Mapped[str] = mapped_column(Text, default="")
    head_sha: Mapped[str] = mapped_column(String(64), default="")


class IssueEmbedding(IdMixin, TimestampMixin, Base):
    """An embedded issue of a repository (duplicate detection)."""

    __tablename__ = "issue_embeddings"
    __table_args__ = (
        UniqueConstraint("repo_id", "issue_number"),
        Index("ix_issue_embeddings_org", "org_id"),
    )
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    repo_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    issue_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024), default="")
    state: Mapped[str] = mapped_column(String(16), default="open")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128))


class PrEmbedding(IdMixin, TimestampMixin, Base):
    """An embedded PR summary (related PRs)."""

    __tablename__ = "pr_embeddings"
    __table_args__ = (
        UniqueConstraint("pr_id"),
        Index("ix_pr_embeddings_org_repo", "org_id", "repo_id"),
    )
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    repo_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    pr_id: Mapped[UUID] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"))
    pr_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
