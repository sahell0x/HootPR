from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.billing.ledger import CreditLedger, Reservation
from app.models import ChatMessage, LlmCall, Review, SecurityScan
from tests.factories import make_installation, make_member, make_org, make_pr, make_repo, make_user
from tests.helpers import login_as
from tests.integration.test_reviews_api import make_platform_owner

pytestmark = pytest.mark.integration


def llm_call(org_id, credits: str | None, **kw) -> LlmCall:  # type: ignore[no-untyped-def]
    return LlmCall(
        org_id=org_id, role="review", model="m", provider_host="h", input_tokens=1000,
        cached_tokens=0, output_tokens=100, cost_usd=Decimal("0.01"), latency_ms=1,
        status="ok", credits=None if credits is None else Decimal(credits), **kw,
    )  # fmt: skip


def hold_and_settle(db: Session, org_id, ref_type, ref_id, hold, actual, minimum, reason):  # type: ignore[no-untyped-def]
    ledger = CreditLedger()
    r = ledger.reserve_up_to(db, org_id, Decimal(hold), Decimal(minimum), ref_type, ref_id)
    assert isinstance(r, Reservation)
    return ledger.settle(db, r, Decimal(actual), Decimal(minimum), final_reason=reason)


async def test_receipts_descriptions_and_owner_usage(
    client: httpx.AsyncClient, app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = make_org(db, balance="1000")
    repo = make_repo(db, org, make_installation(db, org))
    pr = make_pr(db, repo, number=12, title="Fix login")
    legacy = Review(
        pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="a" * 40,
        finished_at=datetime.now(UTC),
    )  # fmt: skip
    chat = ChatMessage(
        org_id=org.id, pr_id=pr.id, provider_comment_id="c1", author_username="alice",
        kind="question", body="why?",
    )  # fmt: skip
    scan = SecurityScan(org_id=org.id, repo_id=repo.id, kind="security_review")
    db.add_all([legacy, chat, scan])
    db.flush()
    # Pre-metering review: calls without stage / credits, flat 100 charge.
    db.add_all([llm_call(org.id, None, review_id=legacy.id) for _ in range(2)])
    legacy.credits_charged = hold_and_settle(
        db, org.id, "review", legacy.id, "100", "100", "100", "review"
    )
    db.add(llm_call(org.id, "7.5", chat_id=chat.id, stage="chat"))
    chat.credits_charged = hold_and_settle(db, org.id, "chat", chat.id, "100", "7.5", "5", "chat")
    db.add(llm_call(org.id, "80", task_id=scan.id, stage="security"))
    scan.credits_charged = hold_and_settle(
        db, org.id, "security_scan", scan.id, "500", "80", "50", "security"
    )
    db.add(llm_call(org.id, "3", stage="reports"))  # unbilled background work
    db.commit()
    user = make_user(db)
    make_member(db, user, org, role="member")
    await login_as(client, app, user.id)

    detail = (await client.get(f"/api/orgs/acme/reviews/{legacy.id}")).json()
    assert detail["credits_charged"] == "100"
    receipt = detail["receipt"]
    assert receipt["legacy"] is True and receipt["charged"] == "100"
    assert [(x["stage"], x["label"], x["credits"]) for x in receipt["lines"]] == [
        ("flat", "Flat-rate review (before usage metering)", "100")
    ]
    assert receipt["lines"][0]["input_tokens"] is None  # owner-only
    same = (await client.get(f"/api/orgs/acme/billing/receipts/review/{legacy.id}")).json()
    assert same == receipt

    chat_r = (await client.get(f"/api/orgs/acme/billing/receipts/chat/{chat.id}")).json()
    assert (chat_r["charged"], chat_r["refunded"], chat_r["legacy"]) == ("8", "92", False)
    assert [(x["label"], x["credits"]) for x in chat_r["lines"]] == [("Chat reply", "8")]
    sec = (await client.get(f"/api/orgs/acme/billing/receipts/security_scan/{scan.id}")).json()
    assert sec["charged"] == "80" and sec["lines"][0]["label"] == "Security review"
    for bad in (f"review/{uuid4()}", f"payment/{uuid4()}"):
        assert (await client.get(f"/api/orgs/acme/billing/receipts/{bad}")).status_code == 404

    bill = (await client.get("/api/orgs/acme/billing")).json()
    assert bill["usage_30d"] is None
    by_ref = {(e["ref_type"], e["reason"]): e for e in bill["ledger"]}
    rev = by_ref[("review", "review")]
    assert rev["description"] == "acme/web #12 · Fix login"
    assert rev["href"] == f"/o/acme/reviews/{legacy.id}" and rev["has_receipt"] is True
    assert by_ref[("chat", "chat")]["description"] == "Chat reply on acme/web #12"
    assert by_ref[("chat", "chat")]["href"] is None
    assert by_ref[("security_scan", "security")]["description"] == "Security review of acme/web"
    signup = [e for e in bill["ledger"] if e["ref_type"] not in ("review", "chat", "security_scan")]
    assert all(e["has_receipt"] is False for e in signup)

    make_platform_owner(db, app, user, monkeypatch)
    usage = (await client.get("/api/orgs/acme/billing")).json()["usage_30d"]
    assert usage["unbilled_credits"] == "3" and usage["billed_credits"] == "88"
    assert usage["charged_credits"] == "188"
    assert usage["cost_usd"] == "0.050000"  # 5 calls
    assert usage["by_source"] == [{"source": "reports", "credits": "3", "cost_usd": "0.010000"}]
    owner_r = (await client.get(f"/api/orgs/acme/billing/receipts/review/{legacy.id}")).json()
    assert owner_r["lines"][0]["input_tokens"] == 2000


async def test_receipt_requires_membership(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    org = make_org(db, balance="1000")
    other = make_org(db, provider_org_id="9002", slug="other", name="other")
    pr = make_pr(db, make_repo(db, org, make_installation(db, org)))
    review = Review(
        pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="a" * 40
    )
    db.add(review)
    db.flush()
    hold_and_settle(db, org.id, "review", review.id, "100", "50", "10", "review")
    db.commit()
    user = make_user(db)
    make_member(db, user, other, role="admin")
    await login_as(client, app, user.id)
    r = await client.get(f"/api/orgs/acme/billing/receipts/review/{review.id}")
    assert r.status_code in (403, 404)
    r = await client.get(f"/api/orgs/other/billing/receipts/review/{review.id}")
    assert r.status_code == 404
