from decimal import Decimal

from app.billing.pricing import (
    STAGE_LABELS,
    Rate,
    RateCard,
    credits_for,
    distribute_whole,
    estimate_review_hold,
    fmt_credits,
    ordered_stages,
    rate_card,
    settle_amount,
    stage_label,
    whole,
)
from app.llm.types import Usage
from app.settings import Settings

S = Settings(_env_file=None)  # type: ignore[arg-type]
CARD = rate_card(S)


def test_credits_for_review_matches_calibration() -> None:
    # spec §1: the average review (~8.5k in / 3.4k cached / 4.9k out) is about 100 credits
    c = credits_for("review", Usage(8500, 3400, 4900), CARD)
    assert c == Decimal("91.440000")
    assert Decimal("80") < c < Decimal("110")


def test_credits_for_cheap_and_embed() -> None:
    assert credits_for("cheap", Usage(1_000_000, 0, 1_000_000), CARD) == Decimal("6000.000000")
    assert credits_for("embed", Usage(1_000_000, 0, 0), CARD) == Decimal("200.000000")
    assert credits_for("embed", Usage(0, 0, 0), CARD) == Decimal("0.000000")


def test_credits_for_rounds_to_6dp_and_clamps_cached() -> None:
    assert credits_for("review", Usage(1, 0, 0), CARD) == Decimal("0.006000")
    assert credits_for("review", Usage(1, 0, 0), CARD).as_tuple().exponent == -6
    # cached never exceeds input
    assert credits_for("review", Usage(100, 500, 0), CARD) == credits_for(
        "review", Usage(100, 100, 0), CARD
    )


def test_rate_card_from_settings_and_custom() -> None:
    assert RateCard() == CARD
    s = Settings(_env_file=None, credits_review_input_per_1m=Decimal("10000"))  # type: ignore[arg-type]
    assert rate_card(s).review == Rate(Decimal("10000"), Decimal("600"), Decimal("12000"))


def test_estimate_review_hold() -> None:
    # files only (GitLab): 40 lines per file assumed -> 100 + 120 * 0.4 + 3 * 5 = 163
    assert estimate_review_hold(None, 3, S) == Decimal("163")
    assert estimate_review_hold(None, None, S) == Decimal("1000")
    assert estimate_review_hold(100, None, S) == Decimal("1000")
    assert estimate_review_hold(0, 0, S) == Decimal("100")
    # 100 + 500 * 0.4 + 10 * 5 = 350
    assert estimate_review_hold(500, 10, S) == Decimal("350")
    # 100 + 3 * 0.4 + 1 * 5 = 106.2 -> rounded up to a whole credit
    assert estimate_review_hold(3, 1, S) == Decimal("107")
    assert estimate_review_hold(100_000, 500, S) == Decimal("1000")  # clamped to max
    tiny = Settings(_env_file=None, review_hold_base=Decimal("0"))  # type: ignore[arg-type]
    assert estimate_review_hold(1, 0, tiny) == Decimal("10")  # clamped to min
    assert estimate_review_hold(3, 1, S).as_tuple().exponent == 0


def test_settle_amount() -> None:
    assert settle_amount(Decimal("284.1"), Decimal("10"), Decimal("600")) == Decimal("285")
    assert settle_amount(Decimal("284.000001"), Decimal("10"), Decimal("600")) == Decimal("285")
    assert settle_amount(Decimal("284"), Decimal("10"), Decimal("600")) == Decimal("284")
    assert settle_amount(Decimal("1"), Decimal("10"), Decimal("600")) == Decimal("10")
    assert settle_amount(Decimal("900"), Decimal("10"), Decimal("600")) == Decimal("600")
    # the hold wins over the minimum
    assert settle_amount(Decimal("0"), Decimal("50"), Decimal("20")) == Decimal("20")
    assert settle_amount(Decimal("284.1"), Decimal("10"), Decimal("600")).as_tuple().exponent == 0


def test_distribute_whole_sums_to_total() -> None:
    vals = [Decimal("40.4"), Decimal("210.3"), Decimal("30.2"), Decimal("3.9")]
    got = distribute_whole(vals, Decimal("285"))
    assert sum(got) == 285
    assert all(g.as_tuple().exponent == 0 for g in got)
    assert distribute_whole([Decimal("1"), Decimal("1"), Decimal("1")], Decimal("10")) == [
        Decimal(4),
        Decimal(3),
        Decimal(3),
    ]
    # minimum applied: tiny metered spread up to the charge
    assert sum(distribute_whole([Decimal("0.3"), Decimal("0.1")], Decimal("10"))) == 10
    assert distribute_whole([Decimal("0")], Decimal("10")) == [Decimal(0)]
    assert distribute_whole([], Decimal("10")) == []


def test_fmt_credits() -> None:
    assert fmt_credits(Decimal("1250.00")) == "1,250"
    assert fmt_credits(Decimal("100")) == "100"
    assert fmt_credits(Decimal("0")) == "0"
    assert fmt_credits(500) == "500"
    assert whole(Decimal("2.5")) == Decimal(3)


def test_stage_labels_and_order() -> None:
    assert stage_label(None) == "Other" and stage_label("weird") == "Other"
    assert stage_label("judge") == "Verification"
    got = ordered_stages(
        {"summarize": Decimal("0.4"), "learnings": Decimal("0.05"), "x": Decimal("1")}
    )
    assert got == [("learnings", Decimal("0.05")), ("summarize", Decimal("0.4")), ("other", 1)]
    assert list(STAGE_LABELS)[:3] == ["learnings", "triage", "plan"]
