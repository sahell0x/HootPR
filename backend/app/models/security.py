"""Repo-level security jobs (spec §10.3): attack surface maps and security architecture reviews."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class SecurityScan(IdMixin, TimestampMixin, Base):
    __tablename__ = "security_scans"
    __table_args__ = (
        Index("ix_security_scans_repo_kind_created", "repo_id", "kind", "created_at"),
        Index("ix_security_scans_org_created", "org_id", "created_at"),
    )
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    repo_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    # surface_map | security_review
    kind: Mapped[str] = mapped_column(String(24))
    # queued | running | completed | failed | no_credits
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    # dashboard | command
    trigger: Mapped[str] = mapped_column(
        String(16), default="dashboard", server_default="dashboard"
    )
    requested_by: Mapped[str] = mapped_column(String(255), default="", server_default="")
    pr_id: Mapped[UUID | None] = mapped_column(ForeignKey("pull_requests.id", ondelete="SET NULL"))
    chat_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    branch: Mapped[str] = mapped_column(String(255), default="", server_default="")
    commit_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # {"surface": {...attack surface map...}, "report": {...SecurityReport...}}
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    error: Mapped[str | None] = mapped_column(Text)
    credits_charged: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), server_default="0"
    )
    input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
