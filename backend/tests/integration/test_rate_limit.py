import pytest
import redis
from uuid_utils.compat import uuid7

from app.billing.rate_limit import Allowed, Limited, RateLimiter
from app.settings import Settings

pytestmark = pytest.mark.integration


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def test_two_reviews_per_hour_then_limited(redis_client: redis.Redis) -> None:
    clock = Clock()
    rl = RateLimiter(redis_client, {"review": 2, "chat": 10}, clock=clock)
    org = uuid7()
    assert rl.check_and_consume(org, "review") == Allowed(remaining=1)
    clock.t += 60
    assert rl.check_and_consume(org, "review") == Allowed(remaining=0)
    clock.t += 60
    limited = rl.check_and_consume(org, "review")
    assert isinstance(limited, Limited) and limited.retry_after_s == 3600 - 120
    clock.t += 3600 - 120 + 1
    assert isinstance(rl.check_and_consume(org, "review"), Allowed)


def test_kinds_and_orgs_are_independent(redis_client: redis.Redis) -> None:
    rl = RateLimiter(redis_client, {"review": 1, "chat": 1}, clock=Clock())
    a, b = uuid7(), uuid7()
    assert isinstance(rl.check_and_consume(a, "review"), Allowed)
    assert isinstance(rl.check_and_consume(a, "chat"), Allowed)
    assert isinstance(rl.check_and_consume(b, "review"), Allowed)
    assert isinstance(rl.check_and_consume(a, "review"), Limited)
    assert rl.remaining(a, "review") == 0 and rl.remaining(b, "chat") == 1


def test_limited_calls_do_not_consume(redis_client: redis.Redis) -> None:
    clock = Clock()
    rl = RateLimiter(redis_client, {"review": 1, "chat": 1}, clock=clock)
    org = uuid7()
    rl.check_and_consume(org, "review")
    for _ in range(5):
        rl.check_and_consume(org, "review")
    clock.t += 3601
    assert rl.check_and_consume(org, "review") == Allowed(remaining=0)


def test_same_timestamp_calls_are_counted_separately(redis_client: redis.Redis) -> None:
    rl = RateLimiter(redis_client, {"review": 2, "chat": 1}, clock=Clock())
    org = uuid7()
    assert rl.check_and_consume(org, "review") == Allowed(remaining=1)
    assert rl.check_and_consume(org, "review") == Allowed(remaining=0)
    assert isinstance(rl.check_and_consume(org, "review"), Limited)


def test_from_settings_uses_configured_limits(
    redis_client: redis.Redis, settings: Settings
) -> None:
    rl = RateLimiter.from_settings(redis_client, settings)
    org = uuid7()
    assert rl.remaining(org, "review") == settings.rate_limit_reviews_per_hour == 2
    assert rl.remaining(org, "chat") == settings.rate_limit_chat_per_hour == 10


def test_zero_limit_is_always_limited(redis_client: redis.Redis) -> None:
    """RATE_LIMIT_REVIEWS_PER_HOUR=0 disables reviews; it must not crash the Lua script."""
    rl = RateLimiter(redis_client, {"review": 0, "chat": 0}, clock=Clock())
    res = rl.check_and_consume(uuid7(), "review")
    assert res == Limited(retry_after_s=3600)


def test_retry_after(redis_client: redis.Redis) -> None:
    clock = Clock()
    rl = RateLimiter(redis_client, {"review": 1, "chat": 0}, window_s=3600, clock=clock)
    org = uuid7()
    assert rl.retry_after(org, "review") == 0
    rl.check_and_consume(org, "review")
    clock.t += 600
    assert rl.retry_after(org, "review") == 3000
    assert rl.retry_after(org, "chat") == 3600  # a limit of 0 disables the action
