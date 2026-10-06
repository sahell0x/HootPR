"""Finishing-touch jobs (Phase 4, spec §10.1): one row per docstrings / unit tests / autofix /
simplify / fix CI / CI analysis / merge conflict / custom recipe run."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class FinishingJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "finishing_jobs"
    __table_args__ = (
        Index("ix_finishing_jobs_pr_created", "pr_id", "created_at"),
        Index("ix_finishing_jobs_org_created", "org_id", "created_at"),
    )
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    pr_id: Mapped[UUID] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"))
    chat_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    # docstrings | unit_tests | autofix | simplify | fix_ci | ci_analysis | merge_conflict | custom
    kind: Mapped[str] = mapped_column(String(24))
    recipe_name: Mapped[str | None] = mapped_column(String(64))
    # command | webhook
    trigger: Mapped[str] = mapped_column(String(16), default="command", server_default="command")
    # commit | stacked_pr | comment
    delivery: Mapped[str] = mapped_column(String(16))
    # queued | running | completed | no_changes | failed | rate_limited | no_credits | skipped
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    requested_by: Mapped[str] = mapped_column(String(255), default="", server_default="")
    head_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    result_sha: Mapped[str | None] = mapped_column(String(64))
    result_pr_number: Mapped[int | None] = mapped_column(Integer)
    result_url: Mapped[str | None] = mapped_column(String(1024))
    # verified | failed | couldnt_verify | not_run
    verification: Mapped[str] = mapped_column(
        String(16), default="not_run", server_default="not_run"
    )
    verification_detail: Mapped[str | None] = mapped_column(Text)
    files_changed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    credits_charged: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), server_default="0"
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # {run_id, instructions, iterations, test_command, conflicted_files, ...}
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
