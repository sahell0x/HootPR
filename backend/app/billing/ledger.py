"""Append-only credit ledger (spec §4.4, decision P5). Callers own the transaction.

Every mutation locks the organization row with ``SELECT ... FOR UPDATE`` so concurrent reserves
(api + worker) serialize and the balance never goes negative. ``organizations.credits_balance``
is a cache of ``SUM(credit_ledger.delta)``; each ledger row stores ``balance_after``.

Token-metered jobs (docs/token-metered-billing.md): ``reserve_up_to`` holds ``min(max, balance)``
(refused only below the job's minimum charge); ``settle`` appends one final row returning the
unused part of the hold (``delta = hold - charge``, ``charge = clamp(ceil(actual), min, hold)``).
All amounts are whole credits: holds/minimums are rounded up, the metered actual is rounded up.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.pricing import CREDIT, ceil_whole, settle_amount
from app.models import CreditLedgerEntry, Organization

HOLD = "review_hold"
REFUND = "refund"


@dataclass(frozen=True)
class Reservation:
    org_id: UUID
    amount: Decimal
    ref_type: str
    ref_id: UUID


@dataclass(frozen=True)
class InsufficientCredits:
    balance: Decimal
    required: Decimal


class CreditLedger:
    def _lock(self, s: Session, org_id: UUID) -> Organization:
        stmt = (
            select(Organization)
            .where(Organization.id == org_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return s.execute(stmt).scalar_one()

    def _append(
        self,
        s: Session,
        org: Organization,
        delta: Decimal,
        reason: str,
        ref_type: str | None,
        ref_id: UUID | None,
    ) -> Decimal:
        new_balance = (Decimal(org.credits_balance) + delta).quantize(CREDIT)
        org.credits_balance = new_balance
        s.add(
            CreditLedgerEntry(
                org_id=org.id,
                delta=delta.quantize(CREDIT),
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
                balance_after=new_balance,
            )
        )
        s.flush()
        return new_balance

    def _entries(self, s: Session, ref_type: str, ref_id: UUID) -> list[CreditLedgerEntry]:
        stmt = select(CreditLedgerEntry).where(
            CreditLedgerEntry.ref_type == ref_type, CreditLedgerEntry.ref_id == ref_id
        )
        return list(s.execute(stmt).scalars())

    def _is_open(self, s: Session, r: Reservation) -> bool:
        reasons = {e.reason for e in self._entries(s, r.ref_type, r.ref_id)}
        return reasons == {HOLD}

    def balance(self, s: Session, org_id: UUID) -> Decimal:
        stmt = select(Organization.credits_balance).where(Organization.id == org_id)
        return Decimal(s.execute(stmt).scalar_one()).quantize(CREDIT)

    def grant(
        self,
        s: Session,
        org_id: UUID,
        amount: Decimal,
        reason: str,
        ref_type: str | None = None,
        ref_id: UUID | None = None,
    ) -> Decimal:
        if amount <= 0:
            raise ValueError("grant amount must be positive")
        return self._append(s, self._lock(s, org_id), amount, reason, ref_type, ref_id)

    def reserve(
        self, s: Session, org_id: UUID, amount: Decimal, ref_type: str, ref_id: UUID
    ) -> Reservation | InsufficientCredits:
        if amount <= 0:
            raise ValueError("reserve amount must be positive")
        amount = ceil_whole(amount)
        org = self._lock(s, org_id)
        for e in self._entries(s, ref_type, ref_id):
            if e.reason == HOLD:
                return Reservation(org_id, -Decimal(e.delta), ref_type, ref_id)
        balance = Decimal(org.credits_balance).quantize(CREDIT)
        if balance < amount:
            return InsufficientCredits(balance=balance, required=amount)
        self._append(s, org, -amount, HOLD, ref_type, ref_id)
        return Reservation(org_id, amount.quantize(CREDIT), ref_type, ref_id)

    def reserve_up_to(
        self,
        s: Session,
        org_id: UUID,
        maximum: Decimal,
        minimum: Decimal,
        ref_type: str,
        ref_id: UUID,
    ) -> Reservation | InsufficientCredits:
        """Hold ``min(maximum, balance)``; refused only when the balance is below ``minimum``.
        Idempotent per ref like ``reserve``."""
        if maximum <= 0 or minimum <= 0:
            raise ValueError("hold amounts must be positive")
        org = self._lock(s, org_id)
        for e in self._entries(s, ref_type, ref_id):
            if e.reason == HOLD:
                return Reservation(org_id, -Decimal(e.delta), ref_type, ref_id)
        balance = Decimal(org.credits_balance).quantize(CREDIT)
        floor = ceil_whole(minimum)
        if balance < floor:
            return InsufficientCredits(balance=balance, required=floor)
        amount = max(min(ceil_whole(maximum), balance), floor)
        self._append(s, org, -amount, HOLD, ref_type, ref_id)
        return Reservation(org_id, amount, ref_type, ref_id)

    def settle(
        self,
        s: Session,
        reservation: Reservation,
        actual: Decimal,
        minimum: Decimal,
        final_reason: str = "review",
    ) -> Decimal:
        """Close an open hold at the metered credits; returns the charge.

        ``charge = clamp(ceil_whole(actual), ceil_whole(minimum), hold)`` (whole credits) and one
        ``final_reason`` row with ``delta = hold - charge`` (0 when all of it was used).
        Idempotent: on an already closed reservation nothing is written and the charge recorded
        back then is returned."""
        org = self._lock(s, reservation.org_id)
        entries = self._entries(s, reservation.ref_type, reservation.ref_id)
        hold = next((-Decimal(e.delta) for e in entries if e.reason == HOLD), None)
        if hold is None:
            return Decimal(0).quantize(CREDIT)
        if {e.reason for e in entries} != {HOLD}:
            closing = [e for e in entries if e.reason != HOLD]
            if any(e.reason == REFUND for e in closing):
                return Decimal(0).quantize(CREDIT)
            return (hold - sum((Decimal(e.delta) for e in closing), Decimal(0))).quantize(CREDIT)
        charge = settle_amount(actual, minimum, hold)
        self._append(s, org, hold - charge, final_reason, reservation.ref_type, reservation.ref_id)
        return charge

    def commit(self, s: Session, reservation: Reservation, final_reason: str = "review") -> None:
        """Charge the full hold (delivered-but-failed paths): ``settle`` at the hold."""
        self.settle(s, reservation, reservation.amount, reservation.amount, final_reason)

    def release(self, s: Session, reservation: Reservation) -> None:
        org = self._lock(s, reservation.org_id)
        if self._is_open(s, reservation):
            held = self.find_open_reservation(s, reservation.ref_type, reservation.ref_id)
            amount = held.amount if held is not None else reservation.amount
            self._append(s, org, amount, REFUND, reservation.ref_type, reservation.ref_id)

    def find_open_reservation(self, s: Session, ref_type: str, ref_id: UUID) -> Reservation | None:
        entries = self._entries(s, ref_type, ref_id)
        if len(entries) == 1 and entries[0].reason == HOLD:
            e = entries[0]
            return Reservation(e.org_id, -Decimal(e.delta), ref_type, ref_id)
        return None
