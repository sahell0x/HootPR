from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, TimestampMixin


class CreditLedgerEntry(IdMixin, CreatedMixin, Base):
    """Append-only; never UPDATE or DELETE rows (spec §4.4)."""

    __tablename__ = "credit_ledger"
    __table_args__ = (
        Index("ix_credit_ledger_ref", "ref_type", "ref_id"),
        Index("ix_credit_ledger_org_created", "org_id", "created_at"),
    )
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    # signup_bonus | purchase | review_hold | review | chat | refund | manual
    reason: Mapped[str] = mapped_column(String(32))
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[UUID | None] = mapped_column()
    balance_after: Mapped[Decimal] = mapped_column(Numeric(8, 2))


class Payment(IdMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64))
    amount_paise: Mapped[int] = mapped_column(Integer)
    credits: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    # created | paid | failed
    status: Mapped[str] = mapped_column(String(16), default="created", server_default="created")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    over_cap: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
