import threading
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from uuid_utils.compat import uuid7

from app.billing.ledger import CreditLedger, InsufficientCredits, Reservation
from app.models import CreditLedgerEntry, Organization
from tests.factories import make_org

pytestmark = pytest.mark.integration
L = CreditLedger()


def reasons(db: Session, org: Organization) -> list[tuple[str, str, str]]:
    rows = db.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.org_id == org.id)
        .order_by(CreditLedgerEntry.id)
    ).scalars()
    return [(r.reason, str(r.delta), str(r.balance_after)) for r in rows]


def test_grant_writes_ledger_and_balance(db: Session) -> None:
    org = make_org(db)
    assert L.grant(db, org.id, Decimal("3"), "signup_bonus", "organization", org.id) == Decimal(
        "3.00"
    )
    db.commit()
    assert reasons(db, org) == [("signup_bonus", "3.00", "3.00")]


def test_grant_rejects_non_positive(db: Session) -> None:
    org = make_org(db)
    with pytest.raises(ValueError):
        L.grant(db, org.id, Decimal("0"), "manual")


def test_reserve_commit_flow(db: Session) -> None:
    org = make_org(db, balance="2")
    ref = uuid7()
    r = L.reserve(db, org.id, Decimal("1"), "review", ref)
    assert isinstance(r, Reservation)
    L.commit(db, r)
    L.commit(db, r)  # idempotent
    L.release(db, r)  # no refund after commit
    db.commit()
    assert L.balance(db, org.id) == Decimal("1.00")
    assert [x[0] for x in reasons(db, org)] == ["manual", "review_hold", "review"]
    assert L.find_open_reservation(db, "review", ref) is None


def test_release_refunds_once(db: Session) -> None:
    org = make_org(db, balance="1")
    r = L.reserve(db, org.id, Decimal("1"), "review", uuid7())
    assert isinstance(r, Reservation)
    L.release(db, r)
    L.release(db, r)
    L.commit(db, r)  # no commit after refund
    db.commit()
    assert L.balance(db, org.id) == Decimal("1.00")
    assert [x[0] for x in reasons(db, org)] == ["manual", "review_hold", "refund"]


def test_release_without_hold_is_noop(db: Session) -> None:
    org = make_org(db, balance="1")
    L.release(db, Reservation(org.id, Decimal("1"), "review", uuid7()))
    db.commit()
    assert L.balance(db, org.id) == Decimal("1.00")


def test_insufficient_credits_writes_nothing(db: Session) -> None:
    org = make_org(db)
    res = L.reserve(db, org.id, Decimal("1"), "review", uuid7())
    assert isinstance(res, InsufficientCredits) and res.balance == Decimal("0.00")
    assert res.required == Decimal("1")
    assert reasons(db, org) == []


def test_reserve_with_balance_below_price_is_insufficient(db: Session) -> None:
    org = make_org(db, balance="50")
    assert isinstance(L.reserve(db, org.id, Decimal("100"), "review", uuid7()), InsufficientCredits)
    db.commit()
    assert L.balance(db, org.id) == Decimal("50")


def test_reserve_rounds_a_fractional_amount_up_to_a_whole_credit(db: Session) -> None:
    org = make_org(db, balance="300")
    r = L.reserve(db, org.id, Decimal("99.2"), "review", uuid7())
    assert isinstance(r, Reservation) and r.amount == Decimal("100")
    db.commit()
    assert reasons(db, org)[-1] == ("review_hold", "-100.00", "200.00")


def test_reserve_is_idempotent_per_ref(db: Session) -> None:
    org = make_org(db, balance="3")
    ref = uuid7()
    a = L.reserve(db, org.id, Decimal("1"), "review", ref)
    b = L.reserve(db, org.id, Decimal("1"), "review", ref)
    db.commit()
    assert a == b and L.balance(db, org.id) == Decimal("2.00")
    assert L.find_open_reservation(db, "review", ref) == a


def test_ledger_sum_equals_cached_balance(db: Session) -> None:
    org = make_org(db, balance="5")
    for i in range(3):
        r = L.reserve(db, org.id, Decimal("1"), "review", uuid7())
        assert isinstance(r, Reservation)
        if i == 1:
            L.release(db, r)
        else:
            L.commit(db, r)
    db.commit()
    total = db.execute(
        select(func.sum(CreditLedgerEntry.delta)).where(CreditLedgerEntry.org_id == org.id)
    ).scalar_one()
    assert total == L.balance(db, org.id) == Decimal("3.00")


def test_concurrent_reserves_never_overdraw(
    session_factory: sessionmaker[Session], db: Session
) -> None:
    org = make_org(db, balance="1")
    results: list[object] = []

    def worker() -> None:
        with session_factory() as s:
            results.append(L.reserve(s, org.id, Decimal("1"), "review", uuid7()))
            s.commit()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(isinstance(r, Reservation) for r in results) == 1
    db.expire_all()
    assert L.balance(db, org.id) == Decimal("0.00")


# --- token metering (docs/token-metered-billing.md §3, §5) ---------------------------------


def test_reserve_up_to_caps_at_balance_and_refuses_below_minimum(db: Session) -> None:
    org = make_org(db, balance="300")
    r = L.reserve_up_to(db, org.id, Decimal("600"), Decimal("10"), "review", uuid7())
    assert isinstance(r, Reservation) and r.amount == Decimal("300")
    poor = make_org(db, balance="5", provider_org_id="9002", slug="poor")
    no = L.reserve_up_to(db, poor.id, Decimal("600"), Decimal("10"), "review", uuid7())
    assert no == InsufficientCredits(balance=Decimal("5"), required=Decimal("10"))
    # holds are whole credits: a fractional maximum / minimum is rounded up
    odd = L.reserve_up_to(db, org.id, Decimal("106.2"), Decimal("0.4"), "review", uuid7())
    assert odd == InsufficientCredits(balance=Decimal("0"), required=Decimal("1"))
    rich = make_org(db, balance="1000", provider_org_id="9003", slug="rich")
    got = L.reserve_up_to(db, rich.id, Decimal("106.2"), Decimal("0.4"), "review", uuid7())
    assert isinstance(got, Reservation) and got.amount == Decimal("107")


def test_settle_refunds_unused_part_in_one_row_and_is_idempotent(db: Session) -> None:
    org = make_org(db, balance="1000")
    ref = uuid7()
    r = L.reserve_up_to(db, org.id, Decimal("600"), Decimal("10"), "review", ref)
    assert isinstance(r, Reservation)
    # the metered actual is rounded up to a whole credit
    assert L.settle(db, r, Decimal("284.1"), Decimal("10")) == Decimal("285")
    assert L.settle(db, r, Decimal("500"), Decimal("10")) == Decimal("285")  # idempotent
    L.release(db, r)  # no refund after settle
    db.commit()
    assert L.balance(db, org.id) == Decimal("715")
    assert reasons(db, org)[1:] == [
        ("review_hold", "-600.00", "400.00"),
        ("review", "315.00", "715.00"),
    ]


def test_settle_applies_minimum_and_clamps_to_hold(db: Session) -> None:
    org = make_org(db, balance="1000")
    low = L.reserve_up_to(db, org.id, Decimal("200"), Decimal("10"), "review", uuid7())
    high = L.reserve_up_to(db, org.id, Decimal("200"), Decimal("5"), "chat", uuid7())
    assert isinstance(low, Reservation) and isinstance(high, Reservation)
    assert L.settle(db, low, Decimal("0.1"), Decimal("10")) == Decimal("10")
    assert L.settle(db, high, Decimal("700"), Decimal("5"), "chat") == Decimal("200")
    db.commit()
    assert reasons(db, org)[-1] == ("chat", "0.00", "790.00")


def test_settle_after_release_charges_nothing(db: Session) -> None:
    org = make_org(db, balance="1")
    r = L.reserve_up_to(db, org.id, Decimal("1"), Decimal("0.10"), "review", uuid7())
    assert isinstance(r, Reservation)
    L.release(db, r)
    assert L.settle(db, r, Decimal("0.5"), Decimal("0.10")) == Decimal("0.00")
    db.commit()
    assert L.balance(db, org.id) == Decimal("1.00")
