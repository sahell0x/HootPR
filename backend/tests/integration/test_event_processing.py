from collections.abc import Callable
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.models import event_adapter
from app.events.processing import process_delivery
from app.models import Installation, Organization, Repository, WebhookDelivery
from app.platforms.github.webhooks import parse_event
from app.worker.celery_app import make_celery
from app.worker.context import WorkerContext
from tests.fixtures import load_fixture

pytestmark = pytest.mark.integration


def delivery(db: Session, event: str) -> str:
    row = WebhookDelivery(
        provider="github", delivery_id=f"github:{event}", event=event, status="received"
    )
    db.add(row)
    db.commit()
    return str(row.id)


def test_installation_created_creates_org_installation_and_repos(
    db: Session, make_wctx: Callable[..., WorkerContext]
) -> None:
    repos = [{"id": 1001, "full_name": "acme/web", "private": True, "default_branch": "main"}]
    ctx = make_wctx(github_repos=lambda iid: repos)
    ev = parse_event("installation", load_fixture("github", "installation.created"), "d-i")
    assert ev is not None
    status = process_delivery(
        ctx, delivery(db, "installation"), event_adapter.dump_python(ev, mode="json")
    )
    assert status == "processed"
    org = db.execute(select(Organization)).scalar_one()
    assert org.slug == "acme" and org.credits_balance == Decimal("300")
    assert db.execute(select(Installation)).scalar_one().github_installation_id == 42
    assert db.execute(select(Repository)).scalar_one().full_name == "acme/web"
    assert db.execute(select(WebhookDelivery)).scalar_one().status == "processed"


def test_installation_deleted_detaches_repos(
    db: Session, make_wctx: Callable[..., WorkerContext]
) -> None:
    repos = [{"id": 1001, "full_name": "acme/web", "private": True, "default_branch": "main"}]
    ctx = make_wctx(github_repos=lambda iid: repos)
    created = parse_event("installation", load_fixture("github", "installation.created"), "d1")
    process_delivery(ctx, delivery(db, "i1"), event_adapter.dump_python(created, mode="json"))
    payload = load_fixture("github", "installation.created") | {"action": "deleted"}
    deleted = parse_event("installation", payload, "d2")
    process_delivery(ctx, delivery(db, "i2"), event_adapter.dump_python(deleted, mode="json"))
    db.expire_all()
    assert db.execute(select(Installation)).scalar_one().status == "revoked"
    assert db.execute(select(Repository)).scalar_one().installation_id is None


def test_handler_errors_mark_delivery_failed(
    db: Session, make_wctx: Callable[..., WorkerContext]
) -> None:
    def boom(iid: int) -> list[dict[str, object]]:
        raise RuntimeError("github down")

    ctx = make_wctx(github_repos=boom)
    ev = parse_event("installation", load_fixture("github", "installation.created"), "d-x")
    assert (
        process_delivery(ctx, delivery(db, "ix"), event_adapter.dump_python(ev, mode="json"))
        == "failed"
    )
    row = db.execute(select(WebhookDelivery)).scalar_one()
    assert row.status == "failed" and "github down" in (row.error or "")


def test_comment_events_are_ignored_in_phase_1(
    db: Session, make_wctx: Callable[..., WorkerContext]
) -> None:
    ev = parse_event("issue_comment", load_fixture("github", "issue_comment.created"), "d-c")
    assert (
        process_delivery(make_wctx(), delivery(db, "c"), event_adapter.dump_python(ev, mode="json"))
        == "ignored"
    )


def test_beat_schedule(int_settings) -> None:  # type: ignore[no-untyped-def]
    app = make_celery(int_settings)
    tasks = {v["task"]: v["schedule"] for v in app.conf.beat_schedule.values()}
    assert tasks == {
        "gitlab.sync_hooks": 3600.0,
        "maintenance.cleanup_llm_logs": 86400.0,
        "maintenance.sweep_stuck_reviews": 600.0,
        "maintenance.docker_heartbeat": 30.0,
        "maintenance.gc_sandboxes": 600.0,
        "maintenance.purge_review_cache": 86400.0,
        "maintenance.embed_missing_learnings": 3600.0,
        "maintenance.sweep_stuck_chats": 600.0,
        "maintenance.sweep_stuck_finishing": 600.0,
        "maintenance.sweep_stuck_change_stack_chats": 600.0,
        "reports.dispatch_due": 900.0,
    }


def test_malformed_event_marks_delivery_failed(
    db: Session, make_wctx: Callable[..., WorkerContext]
) -> None:
    assert process_delivery(make_wctx(), delivery(db, "bad"), {"kind": "nope"}) == "failed"
    assert db.execute(select(WebhookDelivery)).scalar_one().status == "failed"


def test_cleanup_llm_logs_nulls_old_excerpts(db: Session) -> None:
    from datetime import UTC, datetime, timedelta

    from app.models import LlmCall
    from app.worker.maintenance import purge_llm_excerpts

    now = datetime(2026, 9, 28, tzinfo=UTC)
    old = LlmCall(
        role="cheap",
        model="m",
        provider_host="h",
        status="ok",
        request_excerpt="req",
        response_excerpt="resp",
        created_at=now - timedelta(days=31),
    )
    new = LlmCall(
        role="cheap",
        model="m",
        provider_host="h",
        status="ok",
        request_excerpt="req",
        response_excerpt="resp",
        created_at=now - timedelta(days=1),
    )
    db.add_all([old, new])
    db.commit()
    assert purge_llm_excerpts(db, retention_days=30, now=now) == 1
    db.commit()
    db.refresh(old)
    db.refresh(new)
    assert (old.request_excerpt, old.response_excerpt) == (None, None)
    assert new.request_excerpt == "req"
