from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.models import PrEvent
from app.models import Organization, PullRequest, Review
from app.platforms.base import PullRequest as PlatformPR
from app.platforms.base import RepoRef
from app.platforms.diff import build_file_diff
from app.platforms.github.webhooks import parse_event
from app.platforms.local import LocalPlatform
from app.review.pipeline import handle_pr_event, run_review
from app.worker.context import WorkerContext
from tests.factories import make_installation, make_org, make_repo
from tests.fixtures import load_fixture

pytestmark = pytest.mark.integration
REF = RepoRef("github", "1001", "acme/web")
MARK = "<!-- hootpr:walkthrough -->"


def pr_event(
    name: str = "pull_request.opened", head: str | None = None, **pr_fields: object
) -> PrEvent:
    payload = load_fixture("github", name)
    if head:
        payload["pull_request"]["head"]["sha"] = head
    payload["pull_request"].update(pr_fields)
    ev = parse_event("pull_request", payload, "d")
    assert isinstance(ev, PrEvent)
    return ev


def seed(
    db: Session,
    lp: LocalPlatform,
    balance: str = "300",
    head: str = "2" * 40,
    draft: bool = False,
    title: str = "Add login rate limiting",
) -> Organization:
    org = make_org(db, balance=balance)
    make_repo(db, org, make_installation(db, org))
    set_live_pr(lp, head, draft=draft, title=title)
    return org


def set_live_pr(
    lp: LocalPlatform, head: str, draft: bool = False, title: str = "Add login rate limiting"
) -> None:
    lp.add_pull_request(
        REF,
        PlatformPR(
            7,
            title,
            "",
            "alice",
            "open",
            draft,
            "main",
            "feat/rate-limit",
            "1" * 40,
            head,
            (),
            "https://github.com/acme/web/pull/7",
        ),
        [build_file_diff("src/login.py", "@@ -1 +1,2 @@\n-a\n+b\n+c\n", "modified")],
    )


def run_queued(ctx: WorkerContext) -> None:
    for name, args in list(ctx.queue.calls):  # type: ignore[attr-defined]
        if name == "review.run":
            run_review(ctx, UUID(str(args[0])))


def balance(db: Session) -> Decimal:
    db.expire_all()
    return db.execute(select(Organization)).scalar_one().credits_balance


def comment(lp: LocalPlatform) -> str:
    [c] = lp.comments[("1001", 7)]
    return c.body


def test_opened_pr_gets_reviewed_and_is_metered(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    assert handle_pr_event(ctx, pr_event()) == "processed"
    assert [c[0] for c in ctx.queue.calls] == ["review.run"]  # type: ignore[attr-defined]
    assert balance(db) == Decimal("0")  # unknown PR size: holds min(REVIEW_HOLD_MAX, balance)
    run_queued(ctx)
    body = comment(local_platform)
    assert body.startswith(MARK) and "## Walkthrough" in body and "src/login.py" in body
    assert [(s.state, s.title) for s in local_platform.statuses] == [
        ("in_progress", "HootPR review in progress"),
        ("success", "Review completed"),
    ]
    review = db.execute(select(Review)).scalar_one()
    db.refresh(review)
    # the fake LLM uses a few hundred tokens: the minimum charge applies, the rest is returned
    assert review.status == "completed" and review.credits_charged == Decimal("10")
    assert "- **Credits:** 10" in body and "290 of 300 reserved returned" in body
    assert review.files_considered == 1
    pr = db.execute(select(PullRequest)).scalar_one()
    db.refresh(pr)
    assert pr.last_reviewed_sha == "2" * 40 and pr.reviewed_commits_count == 1
    assert balance(db) == Decimal("290")


def test_same_head_sha_is_reviewed_once(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    handle_pr_event(ctx, pr_event("pull_request.opened"))
    run_queued(ctx)
    handle_pr_event(ctx, pr_event())
    assert len(db.execute(select(Review)).scalars().all()) == 1
    assert balance(db) == Decimal("290")


def test_rate_limited_posts_notice_and_passing_check(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform, balance="1000")
    ctx = make_wctx()
    for i, head in enumerate(["a" * 40, "b" * 40, "c" * 40]):
        set_live_pr(local_platform, head)
        handle_pr_event(
            ctx, pr_event("pull_request.synchronize" if i else "pull_request.opened", head=head)
        )
        run_queued(ctx)
        ctx.queue.calls.clear()  # type: ignore[attr-defined]
    statuses = [(s.state, s.title) for s in local_platform.statuses]
    assert statuses[-1] == ("success", "Review rate limited")
    assert "rate limited" in comment(local_platform).lower()
    reviews = db.execute(select(Review).order_by(Review.created_at)).scalars().all()
    assert [r.status for r in reviews] == ["completed", "completed", "rate_limited"]
    assert balance(db) == Decimal("980")


def test_out_of_credits_posts_notice_and_passing_check(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform, balance="0")
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    assert ctx.queue.calls == []  # type: ignore[attr-defined]
    body = comment(local_platform)
    assert "Out of credits" in body and "http://localhost:3000/o/acme/billing" in body
    assert "metered by AI usage" in body and "at least 10 to start" in body
    assert local_platform.statuses[-1].state == "success"
    assert local_platform.statuses[-1].title == "Out of credits"
    assert db.execute(select(Review)).scalar_one().status == "no_credits"


def test_draft_is_skipped_with_neutral_check(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform, draft=True)
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event(draft=True))
    review = db.execute(select(Review)).scalar_one()
    assert (review.status, review.skip_reason) == ("skipped", "draft")
    assert (local_platform.statuses[-1].state, local_platform.statuses[-1].title) == (
        "neutral",
        "Skipped: draft pull request",
    )
    assert balance(db) == Decimal("300")


def test_failure_refunds_and_posts_error(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    local_platform.fail_next = RuntimeError("provider exploded")
    run_queued(ctx)
    review = db.execute(select(Review)).scalar_one()
    db.refresh(review)
    assert review.status == "failed" and "provider exploded" in (review.error or "")
    assert balance(db) == Decimal("300")
    assert "no credit was charged" in comment(local_platform)
    assert local_platform.statuses[-1].state == "neutral"


def test_newer_push_supersedes_queued_review(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform, balance="500")
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    set_live_pr(local_platform, "9" * 40)
    handle_pr_event(ctx, pr_event("pull_request.synchronize", head="9" * 40))
    run_queued(ctx)
    reviews = db.execute(select(Review).order_by(Review.created_at)).scalars().all()
    for r in reviews:
        db.refresh(r)
    assert [(r.status, r.skip_reason) for r in reviews] == [
        ("skipped", "superseded"),
        ("completed", None),
    ]
    assert balance(db) == Decimal("490")


def test_pr_event_for_unknown_repo_is_ignored(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    ctx = make_wctx()
    assert handle_pr_event(ctx, pr_event()) == "ignored"
    assert local_platform.statuses == [] and db.execute(select(Review)).first() is None


def test_disabled_repo_is_ignored(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = make_org(db, balance="300")
    repo = make_repo(db, org, make_installation(db, org))
    repo.enabled = False
    db.commit()
    set_live_pr(local_platform, "2" * 40)
    assert handle_pr_event(make_wctx(), pr_event()) == "ignored"
    assert local_platform.statuses == []


def test_commit_status_false_suppresses_checks(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    local_platform.set_file(REF, ".hootpr.yaml", "main", "reviews:\n  commit_status: false\n")
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    assert local_platform.statuses == [] and MARK in comment(local_platform)


def test_closed_pr_cancels_queued_review(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    handle_pr_event(ctx, pr_event("pull_request.closed"))
    review = db.execute(select(Review)).scalar_one()
    db.refresh(review)
    assert (review.status, review.skip_reason) == ("skipped", "pr_closed")
    assert balance(db) == Decimal("300")
    run_queued(ctx)  # the queued task finds the review no longer queued and does nothing
    assert local_platform.comments[("1001", 7)] == []


def test_inactive_installation_is_ignored(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = make_org(db, balance="300")
    inst = make_installation(db, org)
    make_repo(db, org, inst)
    inst.status = "suspended"
    db.commit()
    set_live_pr(local_platform, "2" * 40)
    assert handle_pr_event(make_wctx(), pr_event()) == "ignored"
    assert local_platform.statuses == []


def test_crashed_running_review_is_retried_once(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    """Spec §7.9: acks_late redelivers a crashed review.run once; a second crash fails it."""
    seed(db, local_platform)
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    review = db.execute(select(Review)).scalar_one()
    review.status = "running"  # the worker died mid-review
    db.commit()
    run_queued(ctx)  # redelivered task
    db.refresh(review)
    assert review.status == "completed" and review.degraded.get("retried_after_crash") is True
    assert balance(db) == Decimal("290")

    set_live_pr(local_platform, "5" * 40)
    ctx2 = make_wctx()
    handle_pr_event(ctx2, pr_event("pull_request.synchronize", head="5" * 40))
    second = db.execute(select(Review).where(Review.head_sha == "5" * 40)).scalar_one()
    second.status = "running"
    second.degraded = {"retried_after_crash": True}
    db.commit()
    run_queued(ctx2)
    db.refresh(second)
    assert second.status == "failed" and "crash" in (second.error or "")
    assert balance(db) == Decimal("290")  # second hold refunded
    assert "no credit was charged" in comment(local_platform)


def test_closed_pr_keeps_queued_review_when_abort_on_close_is_off(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = seed(db, local_platform)
    org.settings = {"reviews": {"abort_on_close": False}}
    db.commit()
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    handle_pr_event(ctx, pr_event("pull_request.closed"))
    assert db.execute(select(Review)).scalar_one().status == "queued"


def test_invalid_yaml_warning_reaches_walkthrough(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    local_platform.set_file(REF, ".hootpr.yaml", "main", "reviews:\n  profile: loud\n")
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    body = comment(local_platform)
    assert "> [!WARNING]" in body and ".hootpr.yaml is invalid" in body


def test_pr_cannot_disable_its_own_review_via_head_yaml(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    """Review Focus #5: the PR's own `.hootpr.yaml` is never enforced (phase-3 R21)."""
    seed(db, local_platform)
    local_platform.set_file(
        REF, ".hootpr.yaml", "2" * 40, "reviews:\n  auto_review:\n    enabled: false\n"
    )
    ctx = make_wctx()
    assert handle_pr_event(ctx, pr_event(head="2" * 40)) == "processed"
    run_queued(ctx)
    review = db.execute(select(Review)).scalar_one()
    db.refresh(review)
    assert review.status == "completed"
    assert "take effect after it is merged" in comment(local_platform)


def _wait_until_blocked_on_lock(db: Session, timeout_s: float = 10.0) -> None:
    import time

    from sqlalchemy import text

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        n = db.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
        ).scalar_one()
        db.rollback()
        if n:
            return
        time.sleep(0.02)
    raise AssertionError("worker never blocked on the PR row lock")


def test_run_review_locks_pr_row_before_org_row(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    session_factory: Callable[[], Session],
) -> None:
    """Lock order must be PR -> organization everywhere (start_review's order), or a
    synchronize event racing a finishing review deadlocks."""
    import threading

    from sqlalchemy import text

    seed(db, local_platform)
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    [(_, args)] = ctx.queue.calls  # type: ignore[attr-defined]
    holder = session_factory()
    pr_id = db.execute(select(PullRequest.id)).scalar_one()
    holder.execute(select(PullRequest).where(PullRequest.id == pr_id).with_for_update())
    t = threading.Thread(target=run_review, args=(ctx, UUID(str(args[0]))))
    t.start()
    try:
        _wait_until_blocked_on_lock(db)
        probe = session_factory()
        try:
            probe.execute(text("SET lock_timeout = '200ms'"))
            # Would time out if run_review had locked the org row before waiting for the PR.
            probe.execute(select(Organization).with_for_update(nowait=True)).scalar_one()
        finally:
            probe.rollback()
            probe.close()
    finally:
        holder.rollback()
        holder.close()
        t.join(timeout=10)
    review = db.execute(select(Review)).scalar_one()
    db.refresh(review)
    assert review.status == "completed"


class ExplodingQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def enqueue(self, task_name: str, *args: object) -> None:
        raise ConnectionError("broker down")


def test_enqueue_failure_fails_review_and_refunds(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx(queue=ExplodingQueue())
    handle_pr_event(ctx, pr_event())
    review = db.execute(select(Review)).scalar_one()
    db.refresh(review)
    assert review.status == "failed" and "broker down" in (review.error or "")
    assert balance(db) == Decimal("300")
    assert "no credit was charged" in comment(local_platform)
    assert local_platform.statuses[-1].state == "neutral"
    # The failed review no longer blocks a retry for the same head SHA.
    ctx2 = make_wctx()
    handle_pr_event(ctx2, pr_event())
    assert [c[0] for c in ctx2.queue.calls] == ["review.run"]  # type: ignore[attr-defined]


def test_sweep_fails_and_refunds_stuck_reviews(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    from datetime import timedelta

    from app.review.pipeline import sweep_stuck_reviews

    seed(db, local_platform, balance="500")
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())  # queued, never delivered
    review = db.execute(select(Review)).scalar_one()
    old = review.created_at - timedelta(hours=3)
    review.created_at = old
    db.commit()
    assert sweep_stuck_reviews(ctx, now=old + timedelta(minutes=10)) == 0  # not stale yet
    assert sweep_stuck_reviews(ctx, now=old + timedelta(hours=3)) == 1
    db.refresh(review)
    assert review.status == "failed" and "timed out" in (review.error or "")
    assert balance(db) == Decimal("500")
    assert "no credit was charged" in comment(local_platform)
    assert sweep_stuck_reviews(ctx, now=old + timedelta(hours=3)) == 0
