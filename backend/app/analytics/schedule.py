"""Report schedules: when a report runs next and which period it covers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

Schedule = Literal["daily", "weekly", "monthly"]
PERIOD_DAYS: dict[str, int] = {"daily": 1, "weekly": 7, "monthly": 30}


def next_run(schedule: str, hour_utc: int, weekday: int, after: datetime) -> datetime:
    """The first scheduled instant strictly after ``after`` (UTC).

    daily: every day at ``hour_utc``; weekly: on ``weekday`` (0 = Monday); monthly: the 1st."""
    after = after.astimezone(UTC)
    cand = after.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if schedule == "daily":
        return cand if cand > after else cand + timedelta(days=1)
    if schedule == "weekly":
        cand += timedelta(days=(weekday - cand.weekday()) % 7)
        return cand if cand > after else cand + timedelta(days=7)
    if schedule == "monthly":
        cand = cand.replace(day=1)
        if cand > after:
            return cand
        year, month = (cand.year + 1, 1) if cand.month == 12 else (cand.year, cand.month + 1)
        return cand.replace(year=year, month=month)
    raise ValueError(f"unknown schedule {schedule!r}")


def period_for(schedule: str, run_at: datetime) -> tuple[datetime, datetime]:
    """The window a scheduled run summarizes: the ``PERIOD_DAYS`` before it."""
    return run_at - timedelta(days=PERIOD_DAYS.get(schedule, 7)), run_at
