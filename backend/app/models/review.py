from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class PullRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repo_id", "number"),)
    repo_id: Mapped[UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    url: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    author_username: Mapped[str] = mapped_column(String(255), default="", server_default="")
    # open | closed | merged
    state: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    labels: Mapped[list[str]] = mapped_column(ARRAY(String(255)), default=list, server_default="{}")
    base_ref: Mapped[str] = mapped_column(String(255), default="", server_default="")
    head_ref: Mapped[str] = mapped_column(String(255), default="", server_default="")
    base_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    head_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    last_reviewed_sha: Mapped[str | None] = mapped_column(String(64))
    reviewed_commits_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    walkthrough_comment_id: Mapped[str | None] = mapped_column(String(64))
    # request_changes_workflow state (phase-3 R18): none | changes_requested | approved
    blocking_state: Mapped[str] = mapped_column(String(24), default="none", server_default="none")


class Review(IdMixin, TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_pr_head", "pr_id", "head_sha"),
        Index("ix_reviews_org_created", "org_id", "created_at"),
    )
    pr_id: Mapped[UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True
    )
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # auto | incremental | command_review | command_full | manual
    trigger: Mapped[str] = mapped_column(String(32))
    # queued | running | completed | failed | skipped | rate_limited | no_credits
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    skip_reason: Mapped[str | None] = mapped_column(String(64))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    head_sha: Mapped[str] = mapped_column(String(64))
    files_considered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    files_reviewed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    findings_posted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    credits_charged: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), server_default="0"
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    degraded: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Trace timeline (plan Q10): [{name, status, started_at, duration_ms, detail}]
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")


class ReviewTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_tasks"
    review_id: Mapped[UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="", server_default="")
    files: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    # pending | running | done | skipped | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    focus: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list, server_default="{}")
    related_symbols: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    summary: Mapped[str | None] = mapped_column(Text)


class Finding(IdMixin, TimestampMixin, Base):
    __tablename__ = "findings"
    review_id: Mapped[UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("review_tasks.id", ondelete="SET NULL"))
    path: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(8), default="RIGHT", server_default="RIGHT")
    severity: Mapped[str] = mapped_column(String(16))  # critical | major | minor | nitpick
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="llm", server_default="llm")
    confidence: Mapped[float | None] = mapped_column(Float)
    judge_verdict: Mapped[str | None] = mapped_column(String(16))  # keep | drop | merge
    judge_reason: Mapped[str | None] = mapped_column(Text)
    posted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    provider_comment_id: Mapped[str | None] = mapped_column(String(64))
    # open | resolved | dismissed
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    evidence: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")


class ReviewCacheEntry(IdMixin, TimestampMixin, Base):
    """Code graph / tool results per (repo, sha), gzip JSON, purged after REVIEW_CACHE_TTL_DAYS."""

    __tablename__ = "review_cache"
    __table_args__ = (
        UniqueConstraint("repo_id", "sha", "kind", "cache_key"),
        Index("ix_review_cache_created", "created_at"),
    )
    repo_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    sha: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # graph | tools
    cache_key: Mapped[str] = mapped_column(String(64))
    payload_gz: Mapped[bytes] = mapped_column(LargeBinary)
