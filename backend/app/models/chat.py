"""Chat messages: every PR/MR comment HootPR acted on (phase-3 spec §8)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ChatMessage(IdMixin, TimestampMixin, Base):
    """One comment HootPR acted on (command or chat) and its reply (spec §5, phase-3 spec §8)."""

    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("pr_id", "provider_comment_id"),)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    pr_id: Mapped[UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True
    )
    provider_comment_id: Mapped[str] = mapped_column(String(64))
    thread_ref: Mapped[str | None] = mapped_column(String(128))
    author_username: Mapped[str] = mapped_column(String(255))
    # command | chat
    kind: Mapped[str] = mapped_column(String(16))
    command: Mapped[str | None] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    reply_comment_id: Mapped[str | None] = mapped_column(String(64))
    credits_charged: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), server_default="0"
    )
    # received | queued | running | completed | failed | ignored | rate_limited | no_credits
    status: Mapped[str] = mapped_column(String(16), default="received", server_default="received")
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Comment context for the chat job: {is_review_comment, path, line, diff_hunk, url, provider}
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
