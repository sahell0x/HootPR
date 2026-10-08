"""Credit pack purchase rules and idempotent fulfillment (spec §6.7). Sync (decision P3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import Row, Select, func, select, update
from sqlalchemy.orm import Session

from app.billing.ledger import CreditLedger
from app.billing.pricing import CREDIT, fmt_credits
from app.models import Organization, Payment
from app.settings import Settings

ZERO = Decimal(0)
# How long an unpaid order reserves a purchase slot (a Razorpay checkout session).
PENDING_ORDER_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class PurchaseCheck:
    allowed: bool
    code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class FulfillResult:
    status: Literal["paid", "already_paid", "unknown_order"]
    credits_added: Decimal
    balance: Decimal
    org_id: UUID | None


@dataclass(frozen=True)
class Pending:
    """Open (``created``, not yet paid) orders."""

    count: int = 0
    credits: Decimal = ZERO


def pending_orders_stmt(org_id: UUID, now: datetime | None = None) -> Select[int, Decimal]:
    """Recent ``created`` payments: an abandoned checkout stops counting after
    ``PENDING_ORDER_TTL``; ``fulfill`` still grants nothing past the lifetime cap."""
    cutoff = (now or datetime.now(UTC)) - PENDING_ORDER_TTL
    return select(func.count(Payment.id), func.coalesce(func.sum(Payment.credits), 0)).where(
        Payment.org_id == org_id, Payment.status == "created", Payment.created_at >= cutoff
    )


def to_pending(row: Row[int, Decimal]) -> Pending:
    return Pending(int(row[0]), Decimal(row[1]))


def purchase_check(
    org: Organization, settings: Settings, pending: Pending | None = None
) -> PurchaseCheck:
    pack_word = "credit pack" if settings.max_purchases_per_org == 1 else "credit packs"
    if org.purchases_count >= settings.max_purchases_per_org:
        return PurchaseCheck(
            False,
            "purchase_cap_reached",
            f"This organization already bought the maximum of "
            f"{settings.max_purchases_per_org} {pack_word}.",
        )
    projected = Decimal(org.credits_balance) + settings.credit_pack_credits
    if projected > settings.max_credit_balance:
        return PurchaseCheck(
            False,
            "balance_cap_exceeded",
            f"Buying a pack would exceed the maximum balance of "
            f"{fmt_credits(settings.max_credit_balance)} credits.",
        )
    return PurchaseCheck(True)


def _lock_org(s: Session, org_id: UUID) -> Organization:
    stmt = (
        select(Organization)
        .where(Organization.id == org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return s.execute(stmt).scalar_one()


def create_payment(
    s: Session, org_id: UUID, user_id: UUID, settings: Settings
) -> Payment | PurchaseCheck:
    """Re-check the caps under the org row lock and create a ``created`` payment row."""
    org = _lock_org(s, org_id)
    check = purchase_check(org, settings)
    if not check.allowed:
        return check
    # Cancel any previous unpaid created payments for this org so they do not linger.
    s.execute(
        update(Payment)
        .where(Payment.org_id == org.id, Payment.status == "created")
        .values(status="cancelled")
    )
    payment = Payment(
        org_id=org.id,
        user_id=user_id,
        amount_paise=settings.credit_pack_price_paise,
        credits=Decimal(settings.credit_pack_credits),
        status="created",
    )
    s.add(payment)
    s.flush()
    return payment


def attach_order(s: Session, payment_id: UUID, order_id: str) -> None:
    payment = s.get(Payment, payment_id)
    if payment is None:
        raise LookupError(f"payment {payment_id} not found")
    payment.razorpay_order_id = order_id
    s.flush()


def fulfill(
    s: Session, ledger: CreditLedger, settings: Settings, order_id: str, payment_id: str | None
) -> FulfillResult:
    """Idempotent: the payment row lock serializes browser verify vs webhook (Review Focus #4).

    A payment that raced past the caps is recorded as paid and flagged ``over_cap``: past the
    lifetime purchase cap it grants nothing, otherwise its credits are clamped to
    ``MAX_CREDIT_BALANCE``.
    """
    stmt = (
        select(Payment)
        .where(Payment.razorpay_order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    payment = s.execute(stmt).scalar_one_or_none()
    if payment is None:
        return FulfillResult("unknown_order", ZERO, ZERO, None)
    org = _lock_org(s, payment.org_id)
    balance = Decimal(org.credits_balance).quantize(CREDIT)
    if payment.status == "paid":
        return FulfillResult("already_paid", ZERO, balance, org.id)
    credits = Decimal(payment.credits)
    if org.purchases_count >= settings.max_purchases_per_org:
        credits = Decimal("0")
        payment.over_cap = True
    elif balance + credits > settings.max_credit_balance:
        credits = max(Decimal("0"), min(credits, settings.max_credit_balance - balance))
        payment.over_cap = True
    payment.status = "paid"
    payment.paid_at = datetime.now(UTC)
    payment.razorpay_payment_id = payment_id or payment.razorpay_payment_id
    org.purchases_count += 1
    if credits > 0:
        balance = ledger.grant(s, org.id, credits, "purchase", "payment", payment.id)
    s.flush()
    return FulfillResult(
        "paid", credits.quantize(CREDIT), Decimal(balance).quantize(CREDIT), org.id
    )
