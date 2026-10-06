"""Billing page API + Razorpay test-mode Checkout (spec §6.7)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.receipts import (
    CHAT,
    CS_CHAT,
    FINISHING,
    RECEIPT_REF_TYPES,
    REVIEW,
    SECURITY,
    load_receipt,
)
from app.api.schemas import (
    Billing,
    CreditPack,
    LedgerEntry,
    Metering,
    Order,
    OrderPrefill,
    OwnerUsage,
    Receipt,
    UsageSource,
    VerifyPaymentRequest,
    VerifyResult,
)
from app.auth.platform import for_viewer
from app.billing.disclaimer import DISCLAIMER_PLAIN
from app.billing.ledger import HOLD, REFUND, CreditLedger
from app.billing.pricing import CREDIT, fmt_credits
from app.billing.razorpay import RazorpayClient, RazorpayError, verify_payment_signature
from app.billing.service import (
    FulfillResult,
    PurchaseCheck,
    attach_order,
    create_payment,
    fulfill,
    pending_orders_stmt,
    purchase_check,
    to_pending,
)
from app.deps import (
    CurrentUser,
    Db,
    OrgBilling,
    OrgMember,
    PlatformOwner,
    SettingsDep,
    get_http,
)
from app.errors import api_error
from app.finishing.commands import LABELS as FINISHING_LABELS
from app.logging import get_logger
from app.models import (
    ChangeStackMessage,
    ChatMessage,
    CreditLedgerEntry,
    FinishingJob,
    LlmCall,
    Membership,
    Payment,
    PullRequest,
    Repository,
    Review,
    SecurityScan,
)

router = APIRouter()
log = get_logger(__name__)
LEDGER_LIMIT = 50
# Rows that close a metered hold (``CreditLedger.settle``): their delta is the returned part.
SETTLE_REASONS = frozenset({"review", "chat", "finishing", "security", "security_review"})
METERING_WINDOW = timedelta(days=30)


PR_TITLE_MAX = 60
_FINISHING: dict[str, str] = {str(k): v for k, v in FINISHING_LABELS.items()}
PAYMENT_REF = "payment"
# Stages of paying jobs whose calls (before per-job attribution) carry no job id.
BILLED_STAGES = ("security", "finishing")
UsageKey = tuple[str | None, UUID | None]


def _title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= PR_TITLE_MAX else text[: PR_TITLE_MAX - 1].rstrip() + "…"


async def _describe(
    db: AsyncSession, org_id: UUID, slug: str, rows: list[CreditLedgerEntry]
) -> dict[UsageKey, tuple[str | None, str | None]]:
    """``(description, href)`` per ledger ref, one query per ref type (no N+1)."""
    ids: dict[str, set[UUID]] = {}
    for r in rows:
        if r.ref_type and r.ref_id:
            ids.setdefault(r.ref_type, set()).add(r.ref_id)
    out: dict[UsageKey, tuple[str | None, str | None]] = {}
    for pay in ids.get(PAYMENT_REF, set()):
        out[(PAYMENT_REF, pay)] = ("Credit pack", None)
    if ids.get(REVIEW):
        q = (
            select(Review.id, Repository.full_name, PullRequest.number, PullRequest.title)
            .join(PullRequest, PullRequest.id == Review.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .where(Review.org_id == org_id, Review.id.in_(ids[REVIEW]))
        )
        for rid, repo, num, title in (await db.execute(q)).all():
            desc = f"{repo} #{num}" + (f" · {_title(title)}" if title.strip() else "")
            out[(REVIEW, rid)] = (desc, f"/o/{slug}/reviews/{rid}")
    if ids.get(CHAT):
        q2 = (
            select(ChatMessage.id, Repository.full_name, PullRequest.number)
            .join(PullRequest, PullRequest.id == ChatMessage.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .where(ChatMessage.org_id == org_id, ChatMessage.id.in_(ids[CHAT]))
        )
        for cid, repo, num in (await db.execute(q2)).all():
            out[(CHAT, cid)] = (f"Chat reply on {repo} #{num}", None)
    if ids.get(CS_CHAT):
        q3 = (
            select(ChangeStackMessage.id, PullRequest.id, Repository.full_name, PullRequest.number)
            .join(PullRequest, PullRequest.id == ChangeStackMessage.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .where(ChangeStackMessage.org_id == org_id, ChangeStackMessage.id.in_(ids[CS_CHAT]))
        )
        for mid, pr_id, repo, num in (await db.execute(q3)).all():
            out[(CS_CHAT, mid)] = (
                f"Change Stack chat on {repo} #{num}",
                f"/o/{slug}/change-stack/{pr_id}",
            )
    if ids.get(FINISHING):
        q4 = (
            select(
                FinishingJob.id,
                FinishingJob.kind,
                FinishingJob.recipe_name,
                Repository.full_name,
                PullRequest.number,
            )
            .join(PullRequest, PullRequest.id == FinishingJob.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .where(FinishingJob.org_id == org_id, FinishingJob.id.in_(ids[FINISHING]))
        )
        for jid, kind, recipe, repo, num in (await db.execute(q4)).all():
            label = (
                f"Recipe {recipe}"
                if kind == "custom" and recipe
                else _FINISHING.get(kind, kind.replace("_", " ").capitalize())
            )
            out[(FINISHING, jid)] = (f"{label} on {repo} #{num}", None)
    if ids.get(SECURITY):
        q5 = (
            select(SecurityScan.id, Repository.full_name)
            .join(Repository, Repository.id == SecurityScan.repo_id)
            .where(SecurityScan.org_id == org_id, SecurityScan.id.in_(ids[SECURITY]))
        )
        for sid, repo in (await db.execute(q5)).all():
            out[(SECURITY, sid)] = (f"Security review of {repo}", f"/o/{slug}/security")
    return out


async def _owner_usage(db: AsyncSession, org_id: UUID, since: datetime) -> OwnerUsage:
    """Metered credits of the window, billed (tied to a paying job) vs unbilled background work
    (learnings, reports, post-merge, issue enrichment), plus provider cost and actual charges."""
    unbilled = (
        LlmCall.review_id.is_(None)
        & LlmCall.chat_id.is_(None)
        & LlmCall.task_id.is_(None)
        & ((LlmCall.stage.is_(None)) | LlmCall.stage.not_in(BILLED_STAGES))
    )
    base = (LlmCall.org_id == org_id) & (LlmCall.created_at >= since) & (LlmCall.status == "ok")
    total_credits, total_cost = (
        await db.execute(
            select(
                func.coalesce(func.sum(LlmCall.credits), 0),
                func.coalesce(func.sum(LlmCall.cost_usd), 0),
            ).where(base)
        )
    ).one()
    source = func.coalesce(LlmCall.stage, LlmCall.role)
    by_source = (
        await db.execute(
            select(
                source,
                func.coalesce(func.sum(LlmCall.credits), 0),
                func.sum(LlmCall.cost_usd),
            )
            .where(base & unbilled)
            .group_by(source)
            .order_by(func.coalesce(func.sum(LlmCall.credits), 0).desc())
        )
    ).all()
    unbilled_credits = sum((Decimal(c or 0) for _, c, _ in by_source), Decimal(0))
    # Net credits spent by metered jobs in the window: holds - returned - refunded.
    spent = (
        await db.execute(
            select(func.coalesce(func.sum(CreditLedgerEntry.delta), 0)).where(
                CreditLedgerEntry.org_id == org_id,
                CreditLedgerEntry.created_at >= since,
                CreditLedgerEntry.reason.in_({HOLD, REFUND, *SETTLE_REASONS}),
            )
        )
    ).scalar_one()
    return OwnerUsage(
        billed_credits=(Decimal(total_credits or 0) - unbilled_credits).quantize(CREDIT),
        unbilled_credits=unbilled_credits.quantize(CREDIT),
        charged_credits=max(-Decimal(spent), Decimal(0)).quantize(CREDIT),
        cost_usd=Decimal(total_cost or 0).quantize(Decimal("0.000001")),
        by_source=[
            UsageSource(
                source=str(src),
                credits=Decimal(c or 0).quantize(CREDIT),
                cost_usd=None if cost is None else Decimal(cost).quantize(Decimal("0.000001")),
            )
            for src, c, cost in by_source
        ],
    )


@router.get("/api/orgs/{org_slug}/billing/receipts/{ref_type}/{ref_id}", response_model=Receipt)
async def receipt(
    ref_type: str,
    ref_id: UUID,
    ctx: OrgMember,
    db: Db,
    owner: PlatformOwner,
    settings: SettingsDep,
) -> Receipt:
    """Credit receipt of one metered job (review, chat, change_stack_chat, finishing,
    security_scan) of this org; token / $ fields only for platform owners."""
    found = await load_receipt(db, ctx.org.id, ref_type, ref_id, settings)
    if found is None:
        raise api_error(404, "not_found", "Receipt not found")
    return for_viewer(found, owner)


@router.get("/api/orgs/{org_slug}/billing", response_model=Billing)
async def billing(ctx: OrgMember, db: Db, settings: SettingsDep, owner: PlatformOwner) -> Billing:
    org = ctx.org
    pending = to_pending((await db.execute(pending_orders_stmt(org.id))).one())
    check = purchase_check(org, settings, pending)
    rows = (
        (
            await db.execute(
                select(CreditLedgerEntry)
                .where(CreditLedgerEntry.org_id == org.id)
                .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
                .limit(LEDGER_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    settle_refs = {
        (r.ref_type, r.ref_id) for r in rows if r.reason in SETTLE_REASONS and r.ref_id is not None
    }
    holds: dict[tuple[str | None, UUID | None], Decimal] = {}
    if settle_refs:
        hold_rows = await db.execute(
            select(
                CreditLedgerEntry.ref_type, CreditLedgerEntry.ref_id, CreditLedgerEntry.delta
            ).where(
                CreditLedgerEntry.org_id == org.id,
                CreditLedgerEntry.reason == HOLD,
                tuple_(CreditLedgerEntry.ref_type, CreditLedgerEntry.ref_id).in_(settle_refs),
            )
        )
        holds = {(t, i): -Decimal(d) for t, i, d in hold_rows.all()}

    def charged(r: CreditLedgerEntry) -> Decimal | None:
        held = holds.get((r.ref_type, r.ref_id)) if r.reason in SETTLE_REASONS else None
        return None if held is None else (held - Decimal(r.delta)).quantize(CREDIT)

    described = await _describe(db, org.id, org.slug, list(rows))
    since = datetime.now(UTC) - METERING_WINDOW
    n_reviews, avg_credits = (
        await db.execute(
            select(func.count(), func.avg(Review.credits_charged)).where(
                Review.org_id == org.id,
                Review.status == "completed",
                Review.finished_at >= since,
            )
        )
    ).one()
    result = Billing(
        balance=Decimal(org.credits_balance).quantize(CREDIT),
        purchases_count=org.purchases_count,
        max_purchases=settings.max_purchases_per_org,
        max_balance=settings.max_credit_balance.quantize(CREDIT),
        pack=CreditPack(
            credits=settings.credit_pack_credits, price_paise=settings.credit_pack_price_paise
        ),
        can_purchase=check.allowed,
        purchase_blocked_reason=check.message,
        disclaimer=DISCLAIMER_PLAIN,
        ledger=[
            LedgerEntry(
                id=str(r.id),
                delta=Decimal(r.delta).quantize(CREDIT),
                reason=r.reason,
                ref_type=r.ref_type,
                ref_id=str(r.ref_id) if r.ref_id else None,
                balance_after=Decimal(r.balance_after).quantize(CREDIT),
                created_at=r.created_at,
                charged=charged(r),
                description=described.get((r.ref_type, r.ref_id), (None, None))[0],
                href=described.get((r.ref_type, r.ref_id), (None, None))[1],
                has_receipt=r.ref_type in RECEIPT_REF_TYPES and r.ref_id is not None,
            )
            for r in rows
        ],
        metering=Metering(
            review_min_charge=settings.review_min_charge.quantize(CREDIT),
            review_hold_max=settings.review_hold_max.quantize(CREDIT),
            chat_min_charge=settings.chat_min_charge.quantize(CREDIT),
            avg_review_credits_30d=(
                Decimal(avg_credits).quantize(CREDIT)
                if n_reviews and avg_credits is not None
                else None
            ),
            reviews_30d=int(n_reviews or 0),
        ),
        usage_30d=await _owner_usage(db, org.id, since) if owner else None,
    )
    return for_viewer(result, owner)


@router.post("/api/orgs/{org_slug}/billing/orders", response_model=Order, status_code=201)
async def create_order(request: Request, ctx: OrgBilling, db: Db, settings: SettingsDep) -> Order:
    if not settings.billing_configured:
        raise api_error(503, "billing_not_configured", "Razorpay test keys are not configured")
    org_id, user_id = ctx.org.id, ctx.user.id

    def _create(s: Session) -> Payment | PurchaseCheck:
        return create_payment(s, org_id, user_id, settings)

    result = await db.run_sync(_create)
    if isinstance(result, PurchaseCheck):
        await db.rollback()
        raise api_error(409, result.code or "purchase_blocked", result.message or "")
    payment_id: UUID = result.id
    await db.commit()
    try:
        order = await RazorpayClient(settings, get_http(request)).create_order(
            amount_paise=settings.credit_pack_price_paise,
            receipt=str(payment_id),
            notes={"org_id": str(org_id), "payment_id": str(payment_id)},
        )
    except RazorpayError as exc:
        log.warning("razorpay_order_failed", org_id=str(org_id), error=str(exc))
        pay = await db.get(Payment, payment_id)
        if pay is not None:
            pay.status = "failed"
            await db.commit()
        raise api_error(502, "provider_error", "Razorpay test mode is unavailable") from exc
    order_id = str(order["id"])

    def _attach(s: Session) -> None:
        attach_order(s, payment_id, order_id)

    await db.run_sync(_attach)
    await db.commit()
    return Order(
        order_id=order_id,
        key_id=settings.razorpay_key_id,
        amount_paise=settings.credit_pack_price_paise,
        credits=settings.credit_pack_credits,
        name="HootPR",
        # Razorpay Checkout rejects descriptions over 255 chars; the full disclaimer is on the page.
        description=(
            f"{fmt_credits(settings.credit_pack_credits)} review credits "
            "(TEST MODE — no real money charged)"
        ),
        prefill=OrderPrefill(email=ctx.user.email, name=ctx.user.display_name),
    )


@router.post("/api/orgs/{org_slug}/billing/orders/{order_id}/cancel", status_code=204)
async def cancel_order(order_id: str, ctx: OrgBilling, db: Db) -> None:
    """Release an abandoned checkout so it stops counting against the purchase caps.

    Only an unpaid ``created`` order is touched; if Razorpay still captures it later, the
    webhook's ``fulfill`` grants it (clamped to the caps) since it only skips ``paid`` rows.
    """
    payment = (
        await db.execute(
            select(Payment)
            .where(
                Payment.org_id == ctx.org.id,
                Payment.razorpay_order_id == order_id,
                Payment.status == "created",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if payment is not None:
        payment.status = "cancelled"
        await db.commit()


@router.post("/api/billing/verify", response_model=VerifyResult)
async def verify(
    body: VerifyPaymentRequest, user: CurrentUser, db: Db, settings: SettingsDep
) -> VerifyResult:
    if not verify_payment_signature(
        settings.razorpay_key_secret.get_secret_value(),
        body.razorpay_order_id,
        body.razorpay_payment_id,
        body.razorpay_signature,
    ):
        raise api_error(400, "invalid_signature", "Payment signature did not verify")
    payment = (
        await db.execute(select(Payment).where(Payment.razorpay_order_id == body.razorpay_order_id))
    ).scalar_one_or_none()
    member = None
    if payment is not None:
        member = (
            await db.execute(
                select(Membership).where(
                    Membership.org_id == payment.org_id, Membership.user_id == user.id
                )
            )
        ).scalar_one_or_none()
    if payment is None or member is None:
        raise api_error(404, "not_found", "Order not found")
    pay_id = payment.id

    def _fulfill(s: Session) -> FulfillResult:
        return fulfill(
            s, CreditLedger(), settings, body.razorpay_order_id, body.razorpay_payment_id
        )

    res = await db.run_sync(_fulfill)
    await db.commit()
    added = res.credits_added
    if res.status == "already_paid":
        prior = (
            await db.execute(
                select(CreditLedgerEntry.delta).where(
                    CreditLedgerEntry.reason == "purchase",
                    CreditLedgerEntry.ref_type == "payment",
                    CreditLedgerEntry.ref_id == pay_id,
                )
            )
        ).scalar_one_or_none()
        added = Decimal(prior or 0).quantize(CREDIT)
    log.info("payment_verified", org_id=str(res.org_id), status=res.status)
    return VerifyResult(status="paid", credits_added=added, balance=res.balance.quantize(CREDIT))
