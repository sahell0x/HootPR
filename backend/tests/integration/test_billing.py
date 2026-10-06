import hashlib
import hmac
import json
import threading
from decimal import Decimal

import httpx
import pytest
import respx
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.billing.ledger import CreditLedger
from app.billing.service import FulfillResult, fulfill
from app.models import CreditLedgerEntry, Organization, Payment
from app.settings import Settings
from tests.factories import make_member, make_org, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration
RZP = "https://api.razorpay.com/v1"


def sig(order_id: str, payment_id: str) -> str:
    return hmac.new(b"rzp-secret", f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


@pytest.fixture
async def admin(client: httpx.AsyncClient, app: FastAPI, db: Session) -> Organization:
    org = make_org(db, balance="300")
    user = make_user(db)
    make_member(db, user, org, role="admin")
    await login_as(client, app, user.id)
    return org


async def create_order(
    client: httpx.AsyncClient, order_id: str = "order_ABC", status: int = 200
) -> httpx.Response:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        route = mock.post(f"{RZP}/orders").mock(
            return_value=httpx.Response(
                status,
                json={"id": order_id, "amount": 4900, "currency": "INR", "status": "created"},
            )
        )
        resp = await client.post("/api/orgs/acme/billing/orders")
        if route.called:
            req = route.calls[0].request
            assert req.headers["Authorization"].startswith("Basic ")
            body = json.loads(req.content)
            assert body["amount"] == 4900 and body["currency"] == "INR" and body["notes"]["org_id"]
    return resp


async def test_billing_summary(client: httpx.AsyncClient, admin: Organization) -> None:
    body = (await client.get("/api/orgs/acme/billing")).json()
    assert body["balance"] == "300" and body["can_purchase"] is True and body["test_mode"] is True
    assert body["pack"] == {"credits": 500, "price_paise": 4900, "currency": "INR"}
    assert body["max_purchases"] == 2 and body["max_balance"] == "1000"
    assert body["ledger"][0]["reason"] == "manual"
    assert body["ledger"][0]["delta"] == "300" and body["ledger"][0]["balance_after"] == "300"
    assert "no real money" in body["disclaimer"]


async def test_order_then_verify_adds_five_credits(
    client: httpx.AsyncClient, admin: Organization, db: Session
) -> None:
    resp = await create_order(client)
    assert resp.status_code == 201
    order = resp.json()
    assert order["order_id"] == "order_ABC" and order["key_id"] == "rzp_test_key123"
    assert order["amount_paise"] == 4900 and "test mode" in order["description"].lower()
    assert order["prefill"] == {"email": "alice@example.com", "name": "Alice"}
    verify = await client.post(
        "/api/billing/verify",
        json={
            "razorpay_order_id": "order_ABC",
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": sig("order_ABC", "pay_1"),
        },
    )
    assert verify.status_code == 200
    assert verify.json() == {"status": "paid", "credits_added": "500", "balance": "800"}
    again = await client.post(
        "/api/billing/verify",
        json={
            "razorpay_order_id": "order_ABC",
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": sig("order_ABC", "pay_1"),
        },
    )
    assert again.json() == {"status": "paid", "credits_added": "500", "balance": "800"}
    org = db.execute(select(Organization)).scalar_one()
    db.refresh(org)
    assert org.purchases_count == 1


async def test_verify_rejects_bad_signature(client: httpx.AsyncClient, admin: Organization) -> None:
    await create_order(client)
    resp = await client.post(
        "/api/billing/verify",
        json={
            "razorpay_order_id": "order_ABC",
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": "nope",
        },
    )
    assert resp.status_code == 400 and resp.json()["detail"]["code"] == "invalid_signature"


async def test_verify_order_of_other_org_is_404(
    client: httpx.AsyncClient, app: FastAPI, admin: Organization, db: Session
) -> None:
    await create_order(client)
    outsider = make_user(db, name="o", email=None)
    await login_as(client, app, outsider.id)
    resp = await client.post(
        "/api/billing/verify",
        json={
            "razorpay_order_id": "order_ABC",
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": sig("order_ABC", "pay_1"),
        },
    )
    assert resp.status_code == 404


async def test_purchase_caps(client: httpx.AsyncClient, admin: Organization, db: Session) -> None:
    org = db.execute(select(Organization)).scalar_one()
    org.purchases_count = 2
    db.commit()
    resp = await create_order(client)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "purchase_cap_reached"
    org.purchases_count = 0
    db.commit()
    CreditLedger().grant(db, org.id, Decimal("300"), "manual")  # balance 600 + 500 > 1000
    db.commit()
    resp = await create_order(client)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "balance_cap_exceeded"
    summary = (await client.get("/api/orgs/acme/billing")).json()
    assert summary["can_purchase"] is False and summary["purchase_blocked_reason"]
    assert db.execute(select(Payment)).first() is None


async def test_razorpay_failure_marks_payment_failed(
    client: httpx.AsyncClient, admin: Organization, db: Session
) -> None:
    resp = await create_order(client, status=500)
    assert resp.status_code == 502 and resp.json()["detail"]["code"] == "provider_error"
    assert db.execute(select(Payment)).scalar_one().status == "failed"


async def test_member_cannot_buy_billing_admin_can(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    org = make_org(db)
    member = make_user(db, name="m", email=None)
    make_member(db, member, org, role="member")
    await login_as(client, app, member.id)
    assert (await client.post("/api/orgs/acme/billing/orders")).status_code == 403
    ba = make_user(db, name="b", email=None)
    make_member(db, ba, org, role="billing_admin")
    await login_as(client, app, ba.id)
    assert (await create_order(client)).status_code == 201


async def test_billing_not_configured(
    client: httpx.AsyncClient, app: FastAPI, admin: Organization, int_settings: Settings
) -> None:
    app.state.settings = int_settings.model_copy(update={"razorpay_key_secret": SecretStr("")})
    resp = await client.post("/api/orgs/acme/billing/orders")
    assert resp.status_code == 503 and resp.json()["detail"]["code"] == "billing_not_configured"


async def test_fulfill_twice_credits_once(
    client: httpx.AsyncClient,
    admin: Organization,
    int_settings: Settings,
    session_factory: sessionmaker[Session],
    db: Session,
) -> None:
    await create_order(client)
    results: list[FulfillResult] = []

    def run() -> None:
        with session_factory() as s:
            results.append(fulfill(s, CreditLedger(), int_settings, "order_ABC", "pay_1"))
            s.commit()

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status for r in results) == ["already_paid", "already_paid", "paid"]
    org = db.execute(select(Organization)).scalar_one()
    db.refresh(org)
    assert org.credits_balance == Decimal("800") and org.purchases_count == 1
    purchases = (
        db.execute(select(CreditLedgerEntry).where(CreditLedgerEntry.reason == "purchase"))
        .scalars()
        .all()
    )
    assert len(purchases) == 1


async def test_fulfill_unknown_order(int_settings: Settings, db: Session) -> None:
    res = fulfill(db, CreditLedger(), int_settings, "order_nope", "pay_1")
    assert res.status == "unknown_order" and res.org_id is None


async def test_over_cap_race_clamps_credits(
    client: httpx.AsyncClient, admin: Organization, int_settings: Settings, db: Session
) -> None:
    await create_order(client)
    org = db.execute(select(Organization)).scalar_one()
    CreditLedger().grant(db, org.id, Decimal("400"), "manual")  # balance 700; a pack makes 1200
    db.commit()
    res = fulfill(db, CreditLedger(), int_settings, "order_ABC", "pay_9")
    db.commit()
    assert res.status == "paid" and res.credits_added == Decimal("300")
    assert res.balance == Decimal("1000")
    assert db.execute(select(Payment)).scalar_one().over_cap is True


async def test_pending_orders_count_against_purchase_cap(
    client: httpx.AsyncClient, admin: Organization, db: Session
) -> None:
    org = db.execute(select(Organization)).scalar_one()
    org.credits_balance = Decimal("0")
    db.commit()
    assert (await create_order(client, "order_1")).status_code == 201
    assert (await create_order(client, "order_2")).status_code == 201
    third = await create_order(client, "order_3")
    assert third.status_code == 409 and third.json()["detail"]["code"] == "purchase_cap_reached"
    summary = (await client.get("/api/orgs/acme/billing")).json()
    assert summary["can_purchase"] is False


async def test_pending_order_credits_count_against_balance_cap(
    client: httpx.AsyncClient, admin: Organization
) -> None:
    assert (await create_order(client, "order_1")).status_code == 201  # 3 + 5 pending = 8
    second = await create_order(client, "order_2")  # 8 + 5 > 10
    assert second.status_code == 409 and second.json()["detail"]["code"] == "balance_cap_exceeded"


async def test_payment_beyond_purchase_cap_grants_nothing(
    client: httpx.AsyncClient, admin: Organization, int_settings: Settings, db: Session
) -> None:
    await create_order(client)
    org = db.execute(select(Organization)).scalar_one()
    org.purchases_count = int_settings.max_purchases_per_org
    org.credits_balance = Decimal("0")
    db.commit()
    res = fulfill(db, CreditLedger(), int_settings, "order_ABC", "pay_9")
    db.commit()
    assert res.status == "paid" and res.credits_added == Decimal("0.00")
    pay = db.execute(select(Payment)).scalar_one()
    assert pay.status == "paid" and pay.over_cap is True
