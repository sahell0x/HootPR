from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class LlmCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_calls"
    org_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    review_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    chat_id: Mapped[UUID | None] = mapped_column(index=True)
    task_id: Mapped[UUID | None] = mapped_column()
    role: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(128))
    provider_host: Mapped[str] = mapped_column(String(255))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16))  # ok | error
    error: Mapped[str | None] = mapped_column(Text)
    # json_schema | json_object | text
    structured_mode: Mapped[str | None] = mapped_column(String(16))
    request_excerpt: Mapped[str | None] = mapped_column(Text)
    response_excerpt: Mapped[str | None] = mapped_column(Text)
    # Token metering: the pipeline stage the call belongs to and its HootPR credits (rate card).
    stage: Mapped[str | None] = mapped_column(String(32))
    credits: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))


class AgentStep(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_steps"
    review_id: Mapped[UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("review_tasks.id", ondelete="CASCADE"))
    step_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # tool_call | tool_result | final
    tool_name: Mapped[str | None] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    output_excerpt: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class ToolRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "tool_runs"
    review_id: Mapped[UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    findings_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stderr_excerpt: Mapped[str | None] = mapped_column(Text)


class WebhookDelivery(IdMixin, TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"
    provider: Mapped[str] = mapped_column(String(16))
    delivery_id: Mapped[str] = mapped_column(String(128), unique=True)
    event: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(64))
    # received | processed | ignored | failed
    status: Mapped[str] = mapped_column(String(16), default="received", server_default="received")
    error: Mapped[str | None] = mapped_column(Text)
