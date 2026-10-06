"""Phase 8: reports, audit logs, public API keys, Change Stack chat (spec §10.5)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, TimestampMixin


class Report(IdMixin, TimestampMixin, Base):
    """A scheduled report definition (CodeRabbit "Reports")."""

    __tablename__ = "reports"
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    # Custom instructions for the narrative; empty = the default weekly-digest template.
    prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    # daily | weekly | monthly
    schedule: Mapped[str] = mapped_column(String(16), default="weekly", server_default="weekly")
    hour_utc: Mapped[int] = mapped_column(Integer, default=9, server_default="9")
    weekday: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 0 = Monday
    repo_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, server_default="{}"
    )
    email_to: Mapped[list[str]] = mapped_column(
        ARRAY(String(320)), default=list, server_default="{}"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ReportRun(IdMixin, TimestampMixin, Base):
    """One generated report (scheduled or ad-hoc custom prompt)."""

    __tablename__ = "report_runs"
    __table_args__ = (Index("ix_report_runs_org_created", "org_id", "created_at"),)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    # scheduled | custom | manual
    trigger: Mapped[str] = mapped_column(String(16), default="custom", server_default="custom")
    # queued | running | completed | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    repo_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, server_default="{}"
    )
    content: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    error: Mapped[str | None] = mapped_column(Text)
    emailed_to: Mapped[list[str]] = mapped_column(
        ARRAY(String(320)), default=list, server_default="{}"
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(IdMixin, CreatedMixin, Base):
    """Append-only record of security-relevant changes; never UPDATE or DELETE rows."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_org_created", "org_id", "created_at"),)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Display name / "api_key:<prefix>" / "system" at the time of the action.
    actor_label: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class ApiKey(IdMixin, TimestampMixin, Base):
    """Per-org public API key; only the SHA-256 of the secret is stored."""

    __tablename__ = "api_keys"
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChangeStackMessage(IdMixin, TimestampMixin, Base):
    """Pinned Change Stack chat: a user question or HootPR's answer (not posted to the PR)."""

    __tablename__ = "change_stack_messages"
    __table_args__ = (Index("ix_change_stack_messages_pr_created", "pr_id", "created_at"),)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    pr_id: Mapped[UUID] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # user | assistant
    role: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    head_sha: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(Text)
    line: Mapped[int | None] = mapped_column(Integer)
    # assistant rows: queued | running | completed | failed; user rows: completed
    status: Mapped[str] = mapped_column(String(16), default="completed", server_default="completed")
    question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("change_stack_messages.id", ondelete="CASCADE")
    )
    error: Mapped[str | None] = mapped_column(Text)
    credits_charged: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), server_default="0"
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
