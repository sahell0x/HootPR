"""Dashboard metrics and review usage (spec §10.5). Every query is filtered by ``org_id``.

The queries run on either an ``AsyncSession`` (API) or a sync ``Session`` (report worker): the
SQL is built once here and executed through the tiny ``Runner`` adapters at the bottom.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.analytics import schemas as A
from app.models import (
    ChatMessage,
    CreditLedgerEntry,
    Finding,
    Organization,
    PullRequest,
    Repository,
    Review,
)

CREDIT = Decimal(1)  # credits are whole numbers
MICRO = Decimal("0.000001")
BLOCKED = ("rate_limited", "no_credits")
SEVERITIES = ("critical", "major", "minor", "nitpick")
TTFR_SAMPLE = 5000
USAGE_LEDGER_LIMIT = 100
USAGE_REVIEWS_LIMIT = 50
TOP_N = 25


# --- pure helpers (unit tested) -------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (``q`` in 0..1); ``None`` for no data."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def duration_stats(values: Sequence[float]) -> A.DurationStats:
    clean = [v for v in values if v is not None and v >= 0]
    return A.DurationStats(
        count=len(clean),
        median_s=percentile(clean, 0.5),
        p90_s=percentile(clean, 0.9),
        mean_s=(sum(clean) / len(clean)) if clean else None,
    )


def acceptance_rate(accepted: int, dismissed: int) -> float | None:
    """Resolved (suggestion committed / thread resolved) over decided findings."""
    decided = accepted + dismissed
    return None if decided == 0 else accepted / decided


def day_range(since: datetime, until: datetime) -> list[str]:
    start: date = since.astimezone(UTC).date()
    end: date = until.astimezone(UTC).date()
    days: list[str] = []
    d = start
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def fill_days(since: datetime, until: datetime, points: dict[str, A.DayPoint]) -> list[A.DayPoint]:
    """One point per UTC day in the period (missing days are zero)."""
    return [points.get(d) or A.DayPoint(day=d) for d in day_range(since, until)]


def sorted_counts(
    pairs: Iterable[tuple[str | None, int]], order: Sequence[str] = ()
) -> list[A.CountItem]:
    """Counts in the canonical ``order`` first, then the rest by count desc."""
    merged: dict[str, int] = {}
    for k, n in pairs:
        key = k or "unknown"
        merged[key] = merged.get(key, 0) + int(n)
    head = [A.CountItem(key=k, count=merged.pop(k)) for k in order if k in merged]
    tail = sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))
    return head + [A.CountItem(key=k, count=n) for k, n in tail]


def period(days: int, now: datetime | None = None) -> A.Period:
    until = now or datetime.now(UTC)
    return A.Period(since=until - timedelta(days=days), until=until, days=days)


def money(v: Any, q: Decimal = MICRO) -> Decimal:
    return Decimal(v or 0).quantize(q)


# --- query plumbing -------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    org_id: UUID
    since: datetime
    until: datetime
    repo_ids: tuple[UUID, ...] = ()


def _reviews_q(sc: Scope, *cols: Any) -> Select[Any]:
    q = (
        select(*cols)
        .select_from(Review)
        .join(PullRequest, PullRequest.id == Review.pr_id)
        .where(
            Review.org_id == sc.org_id,
            Review.created_at >= sc.since,
            Review.created_at < sc.until,
        )
    )
    if sc.repo_ids:
        q = q.where(PullRequest.repo_id.in_(sc.repo_ids))
    return q


def _findings_q(sc: Scope, *cols: Any) -> Select[Any]:
    return (
        _reviews_q(sc, *cols)
        .join(Finding, Finding.review_id == Review.id)
        .where(Finding.posted.is_(True))
    )


class Runner:
    """Executes a SELECT on a sync or async session and returns plain row tuples."""

    def __init__(self, db: AsyncSession | Session) -> None:
        self._db = db

    async def rows(self, q: Any) -> list[tuple[Any, ...]]:
        if isinstance(self._db, AsyncSession):
            res = await self._db.execute(q)
        else:
            res = self._db.execute(q)
        return [tuple(r) for r in res.all()]

    async def one(self, q: Any) -> tuple[Any, ...]:
        rows = await self.rows(q)
        return rows[0] if rows else ()


def _day(col: Any) -> Any:
    return func.to_char(func.date_trunc("day", func.timezone("UTC", col)), "YYYY-MM-DD")


# --- metrics --------------------------------------------------------------------------------


async def compute_metrics(db: AsyncSession | Session, sc: Scope, days: int) -> A.Metrics:
    r = Runner(db)
    by_status = await r.rows(_reviews_q(sc, Review.status, func.count()).group_by(Review.status))
    prs = (await r.one(_reviews_q(sc, func.count(func.distinct(Review.pr_id)))))[0]
    sev = await r.rows(_findings_q(sc, Finding.severity, func.count()).group_by(Finding.severity))
    cat = await r.rows(_findings_q(sc, Finding.category, func.count()).group_by(Finding.category))
    fstat = await r.rows(_findings_q(sc, Finding.status, func.count()).group_by(Finding.status))
    fs = {k: int(n) for k, n in fstat}
    accepted, dismissed = fs.get("resolved", 0), fs.get("dismissed", 0)

    # time to first completed review, per PR first seen in the period
    first = (
        select(Review.pr_id, func.min(Review.finished_at).label("first_at"))
        .where(Review.org_id == sc.org_id, Review.status == "completed")
        .group_by(Review.pr_id)
        .subquery()
    )
    tq = (
        select(func.extract("epoch", first.c.first_at - PullRequest.created_at))
        .select_from(PullRequest)
        .join(first, first.c.pr_id == PullRequest.id)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .where(
            Repository.org_id == sc.org_id,
            PullRequest.created_at >= sc.since,
            PullRequest.created_at < sc.until,
        )
        .limit(TTFR_SAMPLE)
    )
    if sc.repo_ids:
        tq = tq.where(PullRequest.repo_id.in_(sc.repo_ids))
    ttfr = [float(v) for (v,) in await r.rows(tq) if v is not None]

    # per repo
    completed = func.count().filter(Review.status == "completed")
    repo_rows = await r.rows(
        _reviews_q(
            sc,
            Repository.id,
            Repository.full_name,
            func.count(),
            completed,
            func.coalesce(func.sum(Review.findings_posted), 0),
            func.coalesce(func.sum(Review.cost_usd), 0),
        )
        .join(Repository, Repository.id == PullRequest.repo_id)
        .group_by(Repository.id, Repository.full_name)
        .order_by(func.count().desc())
        .limit(TOP_N)
    )
    repo_dec = await r.rows(
        _findings_q(
            sc,
            PullRequest.repo_id,
            func.count().filter(Finding.status == "resolved"),
            func.count().filter(Finding.status == "dismissed"),
        ).group_by(PullRequest.repo_id)
    )
    dec = {rid: (int(a), int(d)) for rid, a, d in repo_dec}
    per_repo = []
    for rid, name, n, done, nf, cost in repo_rows:
        a, d = dec.get(rid, (0, 0))
        per_repo.append(
            A.RepoBreakdown(
                repo_id=str(rid),
                repo_full_name=name,
                reviews=int(n),
                completed=int(done),
                findings=int(nf),
                accepted=a,
                dismissed=d,
                acceptance_rate=acceptance_rate(a, d),
                cost_usd=money(cost),
            )
        )

    # per author
    author_rows = await r.rows(
        _reviews_q(
            sc,
            PullRequest.author_username,
            func.count(func.distinct(PullRequest.id)),
            func.count(),
            func.coalesce(func.sum(Review.findings_posted), 0),
        )
        .group_by(PullRequest.author_username)
        .order_by(func.count().desc())
        .limit(TOP_N)
    )
    serious = dict(
        (a, int(n))
        for a, n in await r.rows(
            _findings_q(sc, PullRequest.author_username, func.count())
            .where(Finding.severity.in_(("critical", "major")))
            .group_by(PullRequest.author_username)
        )
    )
    per_author = [
        A.AuthorBreakdown(
            author=a or "unknown",
            pull_requests=int(p),
            reviews=int(n),
            findings=int(f),
            critical_major=serious.get(a, 0),
        )
        for a, p, n, f in author_rows
    ]

    # daily
    points: dict[str, A.DayPoint] = {}
    day = _day(Review.created_at)
    for d, n, done, blocked in await r.rows(
        _reviews_q(
            sc,
            day,
            func.count(),
            completed,
            func.count().filter(Review.status.in_(BLOCKED)),
        ).group_by(day)
    ):
        points[d] = A.DayPoint(day=d, reviews=int(n), completed=int(done), blocked=int(blocked))
    for d, n in await r.rows(_findings_q(sc, day, func.count()).group_by(day)):
        points.setdefault(d, A.DayPoint(day=d)).findings = int(n)

    total = sum(int(n) for _, n in by_status)
    return A.Metrics(
        period=A.Period(since=sc.since, until=sc.until, days=days),
        reviews_total=total,
        reviews_by_status=sorted_counts(by_status),
        pull_requests=int(prs or 0),
        findings_total=sum(int(n) for _, n in sev),
        findings_by_severity=sorted_counts(sev, SEVERITIES),
        findings_by_category=sorted_counts(cat),
        acceptance=A.AcceptanceStats(
            accepted=accepted,
            dismissed=dismissed,
            open=fs.get("open", 0),
            rate=acceptance_rate(accepted, dismissed),
        ),
        time_to_first_review=duration_stats(ttfr),
        per_repo=per_repo,
        per_author=per_author,
        daily=fill_days(sc.since, sc.until, points),
    )


# --- usage ----------------------------------------------------------------------------------


async def compute_usage(db: AsyncSession | Session, sc: Scope, days: int) -> A.Usage:
    r = Runner(db)
    statuses = dict(
        (k, int(n))
        for k, n in await r.rows(
            _reviews_q(sc, Review.status, func.count()).group_by(Review.status)
        )
    )
    completed = Review.status == "completed"
    tok = await r.one(
        _reviews_q(
            sc,
            func.coalesce(func.sum(Review.input_tokens), 0),
            func.coalesce(func.sum(Review.cached_tokens), 0),
            func.coalesce(func.sum(Review.output_tokens), 0),
            func.coalesce(func.sum(Review.cost_usd), 0),
            func.count().filter(completed),
            func.coalesce(
                func.sum(case((completed, Review.input_tokens + Review.output_tokens), else_=0)),
                0,
            ),
            func.coalesce(func.sum(case((completed, Review.cost_usd), else_=0)), 0),
        )
    )
    in_t, cached_t, out_t, cost, n_done, done_tokens, done_cost = tok
    ledger_where = and_(
        CreditLedgerEntry.org_id == sc.org_id,
        CreditLedgerEntry.created_at >= sc.since,
        CreditLedgerEntry.created_at < sc.until,
    )
    spent, refunded = await r.one(
        select(
            func.coalesce(func.sum(CreditLedgerEntry.delta).filter(CreditLedgerEntry.delta < 0), 0),
            func.coalesce(
                func.sum(CreditLedgerEntry.delta).filter(CreditLedgerEntry.reason == "refund"), 0
            ),
        ).where(ledger_where)
    )
    chat_q = select(func.count(), func.coalesce(func.sum(ChatMessage.credits_charged), 0)).where(
        ChatMessage.org_id == sc.org_id,
        ChatMessage.created_at >= sc.since,
        ChatMessage.created_at < sc.until,
        ChatMessage.status == "completed",
        ChatMessage.credits_charged > 0,
    )
    chats, chat_credits = await r.one(chat_q)
    balance = (
        await r.one(select(Organization.credits_balance).where(Organization.id == sc.org_id))
    )[0]

    points: dict[str, A.DayPoint] = {}
    day = _day(Review.created_at)
    for d, n, done, blocked, c in await r.rows(
        _reviews_q(
            sc,
            day,
            func.count(),
            func.count().filter(completed),
            func.count().filter(Review.status.in_(BLOCKED)),
            func.coalesce(func.sum(Review.cost_usd), 0),
        ).group_by(day)
    ):
        points[d] = A.DayPoint(
            day=d, reviews=int(n), completed=int(done), blocked=int(blocked), cost_usd=money(c)
        )
    lday = _day(CreditLedgerEntry.created_at)
    for d, net in await r.rows(
        select(lday, func.coalesce(func.sum(CreditLedgerEntry.delta), 0))
        .where(ledger_where, CreditLedgerEntry.reason != "purchase")
        .where(CreditLedgerEntry.reason != "signup_bonus")
        .group_by(lday)
    ):
        points.setdefault(d, A.DayPoint(day=d)).credits = money(-Decimal(net), CREDIT)

    ledger = [
        A.UsageLedgerEntry(
            id=str(e.id),
            delta=money(e.delta, CREDIT),
            reason=e.reason,
            ref_type=e.ref_type,
            ref_id=str(e.ref_id) if e.ref_id else None,
            balance_after=money(e.balance_after, CREDIT),
            created_at=e.created_at,
        )
        for (e,) in await r.rows(
            select(CreditLedgerEntry)
            .where(ledger_where)
            .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
            .limit(USAGE_LEDGER_LIMIT)
        )
    ]
    reviews = [
        A.UsageReview(
            id=str(rv.id),
            repo_full_name=name,
            pr_number=num,
            status=rv.status,
            credits_charged=money(rv.credits_charged, CREDIT),
            input_tokens=rv.input_tokens,
            cached_tokens=rv.cached_tokens,
            output_tokens=rv.output_tokens,
            cost_usd=None if rv.cost_usd is None else money(rv.cost_usd),
            created_at=rv.created_at,
        )
        for rv, name, num in await r.rows(
            _reviews_q(sc, Review, Repository.full_name, PullRequest.number)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .order_by(Review.created_at.desc())
            .limit(USAGE_REVIEWS_LIMIT)
        )
    ]
    n_done = int(n_done or 0)
    return A.Usage(
        period=A.Period(since=sc.since, until=sc.until, days=days),
        balance=money(balance, CREDIT),
        review_events=sum(statuses.values()),
        completed=statuses.get("completed", 0),
        rate_limited=statuses.get("rate_limited", 0),
        no_credits=statuses.get("no_credits", 0),
        failed=statuses.get("failed", 0),
        skipped=statuses.get("skipped", 0),
        credits_spent=money(-Decimal(spent or 0) - Decimal(refunded or 0), CREDIT),
        credits_refunded=money(refunded, CREDIT),
        chat_replies=int(chats or 0),
        chat_credits=money(chat_credits, CREDIT),
        input_tokens=int(in_t or 0),
        cached_tokens=int(cached_t or 0),
        output_tokens=int(out_t or 0),
        cost_usd=money(cost),
        avg_tokens_per_review=(int(done_tokens) / n_done) if n_done else None,
        avg_cost_per_review=money(Decimal(done_cost) / n_done) if n_done else None,
        daily=fill_days(sc.since, sc.until, points),
        ledger=ledger,
        reviews=reviews,
    )
