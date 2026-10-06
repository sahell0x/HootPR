"""Per-(org, kind) sliding-window rate limiter on a Redis sorted set (spec §4.4).

Key ``rl:<kind>:<org_id>`` holds one member per consumed call, scored by its timestamp. The check
and the consume happen atomically in one Lua script; a limited call consumes nothing.
"""

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import redis

from app.settings import Settings

RateKind = Literal["review", "chat"]

_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, ARGV[4])
  redis.call('EXPIRE', key, math.ceil(window))
  return {1, limit - count - 1}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if #oldest == 0 then
  return {0, math.ceil(window)}
end
return {0, math.ceil(tonumber(oldest[2]) + window - now)}
"""


@dataclass(frozen=True)
class Allowed:
    remaining: int


@dataclass(frozen=True)
class Limited:
    retry_after_s: int


class RateLimiter:
    def __init__(
        self,
        client: redis.Redis,
        limits: Mapping[str, int],
        *,
        window_s: int = 3600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._r = client
        self._limits = dict(limits)
        self._window = window_s
        self._clock = clock
        self._script = client.register_script(_LUA)

    @classmethod
    def from_settings(cls, client: redis.Redis, settings: Settings) -> "RateLimiter":
        return cls(
            client,
            {
                "review": settings.rate_limit_reviews_per_hour,
                "chat": settings.rate_limit_chat_per_hour,
            },
        )

    @staticmethod
    def _key(org_id: UUID, kind: str) -> str:
        return f"rl:{kind}:{org_id}"

    def check_and_consume(self, org_id: UUID, kind: RateKind) -> Allowed | Limited:
        if self._limits[kind] <= 0:  # a limit of 0 disables the action
            return Limited(retry_after_s=self._window)
        now = self._clock()
        ok, value = self._script(
            keys=[self._key(org_id, kind)],
            args=[repr(now), self._window, self._limits[kind], f"{now!r}:{uuid.uuid4().hex}"],
        )
        if int(ok) == 1:
            return Allowed(remaining=int(value))
        return Limited(retry_after_s=max(1, int(value)))

    def remaining(self, org_id: UUID, kind: RateKind) -> int:
        now = self._clock()
        used = int(self._r.zcount(self._key(org_id, kind), f"({now - self._window!r}", "+inf"))
        return max(0, self._limits[kind] - used)

    def retry_after(self, org_id: UUID, kind: RateKind) -> int:
        """Seconds until a slot frees up; 0 when one is free now."""
        if self._limits[kind] <= 0:
            return self._window
        if self.remaining(org_id, kind) > 0:
            return 0
        now = self._clock()
        oldest = self._r.zrangebyscore(
            self._key(org_id, kind),
            f"({now - self._window!r}",
            "+inf",
            start=0,
            num=1,
            withscores=True,
        )
        return max(1, int(float(oldest[0][1]) + self._window - now)) if oldest else 0
