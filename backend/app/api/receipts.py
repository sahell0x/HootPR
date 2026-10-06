"""Credit receipts (docs/token-metered-billing.md §6) for every metered job: reviews, chat
replies (PR + Change Stack), finishing touches and security reviews.

One builder: the job's ledger rows give reserved / charged / returned, its ``llm_calls`` give the
per-stage lines (whole credits, largest remainder, adding up to the charge). Jobs billed before
usage metering (no call carries credits) get a single flat-rate line instead of a misleading
"Other — 0" line next to a non-zero charge. Token / $ fields are owner-only (``for_viewer``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas as S
from app.billing.ledger import HOLD, REFUND
from app.billing.pricing import CREDIT, STAGE_LABELS, ceil_whole, distribute_whole, stage_key
from app.models import CreditLedgerEntry, FinishingJob, LlmCall, Review
from app.settings import Settings

MICRO = Decimal("0.000001")
FLAT = "flat"
FLAT_LABEL = "Flat-rate review (before usage metering)"
FLAT_LABEL_OTHER = "Flat-rate charge (before usage metering)"

# Ledger ``ref_type`` values of metered jobs (the worker-side constants are not imported here:
# app.review.pipeline.REF_TYPE, app.chat.actions.CHAT_REF_TYPE,
# app.change_stack.chat.CS_CHAT_REF_TYPE, app.finishing.handler.FINISHING_REF_TYPE,
# app.security.store.REF_TYPE).
REVIEW = "review"
CHAT = "chat"
CS_CHAT = "change_stack_chat"
FINISHING = "finishing"
SECURITY = "security_scan"
RECEIPT_REF_TYPES = frozenset({REVIEW, CHAT, CS_CHAT, FINISHING, SECURITY})


def _usd(value: Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(value).quantize(MICRO)


@dataclass
class _Acc:
    credits: Decimal = Decimal(0)
    metered: bool = False
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = None

    def add(self, c: LlmCall) -> None:
        if c.credits is not None:
            self.metered = True
            self.credits += Decimal(c.credits)
        self.input_tokens += c.input_tokens
        self.cached_tokens += c.cached_tokens
        self.output_tokens += c.output_tokens
        if c.cost_usd is not None:
            self.cost_usd = (self.cost_usd or Decimal(0)) + Decimal(c.cost_usd)


@dataclass
class _Sums:
    by_stage: dict[str, _Acc] = field(default_factory=dict)
    total: _Acc = field(default_factory=_Acc)


def _line(stage: str, label: str, credits: Decimal, acc: _Acc) -> S.ReceiptLine:
    return S.ReceiptLine(
        stage=stage,
        label=label,
        credits=credits,
        input_tokens=acc.input_tokens,
        cached_tokens=acc.cached_tokens,
        output_tokens=acc.output_tokens,
        cost_usd=_usd(acc.cost_usd),
    )


def build_receipt(
    entries: list[CreditLedgerEntry],
    calls: list[LlmCall],
    min_charge: Decimal,
    *,
    budget_reached: bool = False,
    flat_label: str = FLAT_LABEL,
) -> S.Receipt | None:
    """Receipt from a job's ledger rows + its LLM calls (None: the job never held credits)."""
    hold = next((e for e in entries if e.reason == HOLD), None)
    if hold is None:
        return None
    zero = Decimal(0).quantize(CREDIT)
    reserved = (-Decimal(hold.delta)).quantize(CREDIT)
    closing = [e for e in entries if e.reason != HOLD]
    if any(e.reason == REFUND for e in closing):
        charged, refunded = zero, reserved
    elif closing:
        refunded = sum((Decimal(e.delta) for e in closing), Decimal(0)).quantize(CREDIT)
        charged = reserved - refunded
    else:  # still running: nothing settled yet
        charged = refunded = zero
    sums = _Sums()
    for c in calls:
        if c.status != "ok":
            continue
        sums.by_stage.setdefault(stage_key(c.stage), _Acc()).add(c)
        sums.total.add(c)
    metered = sums.total.credits
    closed = bool(closing)
    # Nothing metered (billed before usage metering) or nothing the lines could be scaled to:
    # one flat line carries the charge rather than "Other — 0" next to a non-zero charge.
    if closed and charged > 0 and (not sums.total.metered or metered <= 0):
        return S.Receipt(
            reserved=reserved,
            charged=charged,
            refunded=refunded,
            minimum_applied=False,
            budget_reached=budget_reached,
            legacy=not sums.total.metered,
            lines=[_line(FLAT, flat_label, charged, sums.total)],
        )
    floor = min(ceil_whole(min_charge), reserved)
    keys = [k for k in STAGE_LABELS if k in sums.by_stage]
    # Whole-credit lines that add up to the charge (still running: to the metered credits).
    shown = distribute_whole(
        [sums.by_stage[k].credits for k in keys], charged if charged > 0 else ceil_whole(metered)
    )
    return S.Receipt(
        reserved=reserved,
        charged=charged,
        refunded=refunded,
        minimum_applied=charged > 0 and charged == floor and ceil_whole(metered) < charged,
        budget_reached=budget_reached,
        legacy=False,
        lines=[
            _line(k, STAGE_LABELS[k], credits, sums.by_stage[k])
            for k, credits in zip(keys, shown, strict=True)
        ],
    )


async def ledger_entries(
    db: AsyncSession, org_id: UUID, ref_type: str, ref_id: UUID
) -> list[CreditLedgerEntry]:
    stmt = select(CreditLedgerEntry).where(
        CreditLedgerEntry.org_id == org_id,
        CreditLedgerEntry.ref_type == ref_type,
        CreditLedgerEntry.ref_id == ref_id,
    )
    return list((await db.execute(stmt)).scalars())


async def _calls(db: AsyncSession, cond: ColumnElement[bool]) -> list[LlmCall]:
    stmt = select(LlmCall).where(cond).order_by(LlmCall.created_at, LlmCall.id)
    return list((await db.execute(stmt)).scalars())


def _window(entries: list[CreditLedgerEntry]) -> tuple[datetime, datetime]:
    hold = next(e for e in entries if e.reason == HOLD)
    end = max((e.created_at for e in entries if e.reason != HOLD), default=datetime.now(UTC))
    return hold.created_at, end


async def load_receipt(
    db: AsyncSession, org_id: UUID, ref_type: str, ref_id: UUID, settings: Settings
) -> S.Receipt | None:
    """The receipt of any metered job of ``org_id`` (None: unknown kind or never held)."""
    if ref_type not in RECEIPT_REF_TYPES:
        return None
    entries = await ledger_entries(db, org_id, ref_type, ref_id)
    if not any(e.reason == HOLD for e in entries):
        return None
    budget_reached = False
    flat = FLAT_LABEL_OTHER
    if ref_type == REVIEW:
        review = await db.get(Review, ref_id)
        budget_reached = (
            (review.degraded or {}).get("credit_budget") == "reached" if review else False
        )
        calls = await _calls(db, LlmCall.review_id == ref_id)
        minimum, flat = settings.review_min_charge, FLAT_LABEL
    elif ref_type in (CHAT, CS_CHAT):
        calls = await _calls(db, LlmCall.chat_id == ref_id)
        minimum = settings.chat_min_charge
    elif ref_type == FINISHING:
        job = await db.get(FinishingJob, ref_id)
        cond: ColumnElement[bool] = LlmCall.task_id == ref_id
        if job is not None and job.chat_message_id is not None:
            # Before per-job attribution the calls only carried the command's chat id.
            cond = or_(
                cond,
                and_(
                    LlmCall.task_id.is_(None),
                    LlmCall.review_id.is_(None),
                    LlmCall.chat_id == job.chat_message_id,
                ),
            )
        calls = await _calls(db, cond)
        # CI failure analysis settles like a chat reply.
        as_chat = any(e.reason == CHAT for e in entries)
        minimum = settings.chat_min_charge if as_chat else settings.finishing_min_charge
    else:  # SECURITY
        calls = await _calls(db, LlmCall.task_id == ref_id)
        if not calls:
            # Before per-scan attribution: the org's security calls while the hold was open.
            start, end = _window(entries)
            calls = await _calls(
                db,
                and_(
                    LlmCall.org_id == org_id,
                    LlmCall.stage == "security",
                    LlmCall.task_id.is_(None),
                    LlmCall.review_id.is_(None),
                    LlmCall.chat_id.is_(None),
                    LlmCall.created_at >= start,
                    LlmCall.created_at <= end,
                ),
            )
        minimum = settings.security_min_charge
    return build_receipt(entries, calls, minimum, budget_reached=budget_reached, flat_label=flat)
