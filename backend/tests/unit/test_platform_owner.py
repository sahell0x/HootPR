from datetime import UTC, datetime
from decimal import Decimal

from app.analytics import schemas as A
from app.api import schemas as S
from app.auth.platform import for_viewer, platform_owner_set, strip_internal
from app.settings import Settings


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_platform_owner_set_parses_provider_username_pairs() -> None:
    s = make(platform_owners=" github:Sahell0x , gitlab:bob,bogus,:x,github: ")
    assert platform_owner_set(s) == {("github", "sahell0x"), ("gitlab", "bob")}
    assert platform_owner_set(make()) == frozenset()


NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _usage() -> A.Usage:
    return A.Usage(
        period=A.Period(since=NOW, until=NOW, days=1),
        balance=Decimal("5"),
        review_events=1,
        completed=1,
        rate_limited=0,
        no_credits=0,
        failed=0,
        skipped=0,
        credits_spent=Decimal("1"),
        credits_refunded=Decimal("0"),
        chat_replies=0,
        chat_credits=Decimal("0"),
        input_tokens=10,
        cached_tokens=1,
        output_tokens=2,
        cost_usd=Decimal("0.01"),
        avg_tokens_per_review=12.0,
        avg_cost_per_review=Decimal("0.01"),
        daily=[A.DayPoint(day="2026-09-01", credits=Decimal("1"), cost_usd=Decimal("0.01"))],
        ledger=[],
        reviews=[
            A.UsageReview(
                id="r",
                repo_full_name="a/b",
                pr_number=1,
                status="completed",
                credits_charged=Decimal("1"),
                input_tokens=10,
                cached_tokens=1,
                output_tokens=2,
                cost_usd=Decimal("0.01"),
                created_at=NOW,
            )
        ],
    )


def test_strip_internal_nulls_llm_fields_recursively_and_keeps_credits() -> None:
    u = strip_internal(_usage())
    assert u.input_tokens is None and u.cost_usd is None and u.avg_cost_per_review is None
    assert u.daily[0].cost_usd is None and u.daily[0].credits == Decimal("1")
    assert u.reviews[0].cost_usd is None and u.reviews[0].output_tokens is None
    assert u.credits_spent == Decimal("1") and u.reviews[0].credits_charged == Decimal("1")
    assert for_viewer(_usage(), owner=True).cost_usd == Decimal("0.01")


def test_strip_internal_empties_llm_calls() -> None:
    call = S.LlmCall(
        id="c",
        task_id=None,
        role="review",
        model="secret-model",
        provider_host="h",
        input_tokens=1,
        cached_tokens=0,
        output_tokens=1,
        cost_usd=None,
        latency_ms=1,
        status="ok",
        error=None,
        structured_mode=None,
        created_at=NOW,
    )
    trace = S.Trace(stages=[], tasks=[], llm_calls=[call], agent_steps=[], tool_runs=[])
    assert strip_internal(trace).llm_calls == []
    assert "secret-model" not in strip_internal(trace).model_dump_json()
