from decimal import Decimal
from uuid import uuid4

from app.api.receipts import FLAT_LABEL, build_receipt
from app.models import CreditLedgerEntry, LlmCall

REF = uuid4()


def entry(reason: str, delta: str) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        org_id=uuid4(),
        delta=Decimal(delta),
        reason=reason,
        ref_type="review",
        ref_id=REF,
        balance_after=Decimal(0),
    )


def call(stage: str | None, credits: str | None, tokens: int = 100) -> LlmCall:
    return LlmCall(
        role="review",
        model="m",
        provider_host="h",
        input_tokens=tokens,
        cached_tokens=0,
        output_tokens=10,
        cost_usd=Decimal("0.001"),
        status="ok",
        stage=stage,
        credits=None if credits is None else Decimal(credits),
    )


def test_metered_lines_add_up_to_the_charge() -> None:
    entries = [entry("review_hold", "-600"), entry("review", "315")]
    calls = [call("summarize", "40"), call("agents", "210"), call("agents", "34.1")]
    r = build_receipt(entries, calls, Decimal(10))
    assert r is not None and not r.legacy
    assert (r.reserved, r.charged, r.refunded) == (Decimal(600), Decimal(285), Decimal(315))
    assert [(x.stage, x.credits) for x in r.lines] == [
        ("agents", Decimal(245)),
        ("summarize", Decimal(40)),
    ]


def test_legacy_review_gets_one_flat_line() -> None:
    entries = [entry("review_hold", "-100"), entry("review", "0")]
    calls = [call(None, None, 1000), call(None, None, 500)]
    r = build_receipt(entries, calls, Decimal(10))
    assert r is not None and r.legacy and r.charged == Decimal(100)
    [line] = r.lines
    assert (line.stage, line.label, line.credits) == ("flat", FLAT_LABEL, Decimal(100))
    assert line.input_tokens == 1500 and line.output_tokens == 20
    assert line.cost_usd == Decimal("0.002000")


def test_no_calls_at_all_is_legacy_flat_rate() -> None:
    r = build_receipt([entry("review_hold", "-50"), entry("chat", "0")], [], Decimal(5))
    assert r is not None and r.legacy and [x.credits for x in r.lines] == [Decimal(50)]


def test_zero_metered_credits_never_shows_zero_line_next_to_charge() -> None:
    entries = [entry("review_hold", "-20"), entry("chat", "10")]
    r = build_receipt(entries, [call("chat", "0")], Decimal(10), flat_label="Flat")
    assert r is not None and not r.legacy
    assert [(x.label, x.credits) for x in r.lines] == [("Flat", Decimal(10))]


def test_chat_minimum_and_refund_and_running() -> None:
    r = build_receipt(
        [entry("review_hold", "-100"), entry("chat", "95")], [call("chat", "1.2")], Decimal(5)
    )
    assert r is not None and r.charged == Decimal(5) and r.minimum_applied
    assert [(x.stage, x.label, x.credits) for x in r.lines] == [("chat", "Chat reply", Decimal(5))]
    refunded = build_receipt([entry("review_hold", "-100"), entry("refund", "100")], [], Decimal(5))
    assert refunded is not None and refunded.charged == 0 and refunded.lines == []
    assert not refunded.legacy
    running = build_receipt([entry("review_hold", "-100")], [call("chat", "3.4")], Decimal(5))
    assert running is not None and running.charged == 0
    assert [x.credits for x in running.lines] == [Decimal(4)]
    assert build_receipt([], [call("chat", "1")], Decimal(5)) is None
