from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.analytics import schemas as A
from app.analytics.api_keys import (
    DISPLAY_PREFIX_LEN,
    extract_key,
    generate_key,
    hash_key,
    looks_like_key,
    matches,
)
from app.analytics.audit import build, changed_keys
from app.analytics.export import safe_cell, to_csv, to_json
from app.analytics.metrics import (
    acceptance_rate,
    duration_stats,
    fill_days,
    percentile,
    sorted_counts,
)
from app.analytics.reports import parse_smtp_url, render_report
from app.analytics.schedule import next_run, period_for


def test_percentile_and_duration_stats() -> None:
    assert percentile([], 0.5) is None
    assert percentile([5.0], 0.9) == 5.0
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    st = duration_stats([10, 20, 30, -1])
    assert st.count == 3 and st.median_s == 20 and st.mean_s == 20


def test_acceptance_rate() -> None:
    assert acceptance_rate(0, 0) is None
    assert acceptance_rate(3, 1) == 0.75


def test_fill_days_zero_fills_period() -> None:
    since = datetime(2026, 9, 1, 12, tzinfo=UTC)
    pts = fill_days(
        since, since + timedelta(days=2), {"2026-09-02": A.DayPoint(day="2026-09-02", reviews=4)}
    )
    assert [p.day for p in pts] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert [p.reviews for p in pts] == [0, 4, 0]


def test_sorted_counts_canonical_order_first() -> None:
    out = sorted_counts(
        [("minor", 2), ("critical", 1), (None, 5), ("weird", 7)], ("critical", "major", "minor")
    )
    assert [c.key for c in out] == ["critical", "minor", "weird", "unknown"]


def test_csv_cells_cannot_be_formulas() -> None:
    assert safe_cell('=HYPERLINK("x")') == '\'=HYPERLINK("x")'
    assert safe_cell("+1") == "'+1"
    assert safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert safe_cell(Decimal("-0.50")) == "-0.50"  # numbers stay numeric
    assert safe_cell(None) == "" and safe_cell(True) == "true"
    csv = to_csv(["a", "b"], [{"a": "-cmd", "b": ["x"]}])
    assert csv.splitlines() == ["a,b", '\'-cmd,"[""x""]"']
    assert to_json([{"d": Decimal("1.5"), "t": datetime(2026, 1, 1, tzinfo=UTC)}]) == (
        '[{"d": "1.5", "t": "2026-01-01T00:00:00+00:00"}]'
    )


def test_api_keys_hash_and_extract() -> None:
    k = generate_key()
    assert looks_like_key(k.secret) and k.prefix == k.secret[:DISPLAY_PREFIX_LEN]
    assert k.key_hash == hash_key(k.secret) and k.secret not in k.key_hash
    assert matches(k.secret, k.key_hash) and not matches(k.secret + "x", k.key_hash)
    assert generate_key().secret != k.secret
    assert extract_key(f"Bearer {k.secret}", None) == k.secret
    assert extract_key(None, k.secret) == k.secret
    assert extract_key("Basic abc", None) is None
    assert not looks_like_key("hpr_short") and not looks_like_key(None)


def test_schedule_next_run() -> None:
    t = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)  # Wednesday
    assert next_run("daily", 9, 0, t) == datetime(2026, 10, 1, 9, tzinfo=UTC)
    assert next_run("daily", 11, 0, t) == datetime(2026, 9, 30, 11, tzinfo=UTC)
    assert next_run("weekly", 9, 0, t) == datetime(2026, 10, 5, 9, tzinfo=UTC)
    assert next_run("weekly", 11, 2, t) == datetime(2026, 9, 30, 11, tzinfo=UTC)
    assert next_run("monthly", 9, 0, t) == datetime(2026, 10, 1, 9, tzinfo=UTC)
    assert next_run("monthly", 9, 0, datetime(2026, 12, 5, tzinfo=UTC)) == datetime(
        2027, 1, 1, 9, tzinfo=UTC
    )
    since, until = period_for("weekly", t)
    assert until - since == timedelta(days=7)


def test_audit_build_and_changed_keys() -> None:
    import uuid

    row = build(uuid.uuid4(), "x.y", details={"long": "a" * 900})
    assert row.actor_label == "system" and len(row.details["long"]) < 600
    assert changed_keys({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == ["b", "c"]


def test_smtp_url_parsing() -> None:
    assert parse_smtp_url("") is None and parse_smtp_url("http://x") is None
    c = parse_smtp_url("smtps://u%40x:p%3Aw@mail.example.com")
    assert (
        c is not None
        and c.port == 465
        and c.implicit_tls
        and c.username == "u@x"
        and c.password == "p:w"
    )
    c2 = parse_smtp_url("smtp://mail.example.com")
    assert c2 is not None and c2.port == 587 and not c2.implicit_tls


def test_render_report_without_narrative_keeps_numbers() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    m = A.Metrics(
        period=A.Period(since=now - timedelta(days=7), until=now, days=7),
        reviews_total=3,
        reviews_by_status=[
            A.CountItem(key="completed", count=2),
            A.CountItem(key="no_credits", count=1),
        ],
        pull_requests=2,
        findings_total=1,
        findings_by_severity=[A.CountItem(key="major", count=1)],
        findings_by_category=[A.CountItem(key="security", count=1)],
        acceptance=A.AcceptanceStats(accepted=1, dismissed=1, open=0, rate=0.5),
        time_to_first_review=duration_stats([600]),
        per_repo=[],
        per_author=[],
        daily=[],
    )
    md = render_report("Weekly", m, None)
    assert md.startswith("# Weekly") and "could not be generated" in md
    assert "| Blocked (rate limit / credits) | 1 |" in md and "50%" in md and "10 min" in md
