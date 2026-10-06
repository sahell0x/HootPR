from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.models import Organization, Payment, WebhookDelivery
from tests.factories import make_org, make_repo
from tests.fixtures import fixture_bytes, sign_github, sign_razorpay

pytestmark = pytest.mark.integration


def gh_headers(
    body: bytes, event: str, delivery: str = "d-1", secret: str = "gh-webhook-secret"
) -> dict[str, str]:
    return {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": sign_github(secret, body),
        "Content-Type": "application/json",
    }


async def test_github_invalid_signature_is_401_and_not_stored(
    client: httpx.AsyncClient, db: Session
) -> None:
    body = fixture_bytes("github", "pull_request.opened")
    resp = await client.post(
        "/api/webhooks/github",
        content=body,
        headers=gh_headers(body, "pull_request", secret="wrong"),
    )
    assert resp.status_code == 401 and resp.json()["detail"]["code"] == "invalid_signature"
    missing = await client.post(
        "/api/webhooks/github", content=body, headers={"X-GitHub-Event": "pull_request"}
    )
    assert missing.status_code == 401
    assert db.execute(select(WebhookDelivery)).first() is None


async def test_github_pr_opened_is_queued_once(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    body = fixture_bytes("github", "pull_request.opened")
    first = await client.post(
        "/api/webhooks/github", content=body, headers=gh_headers(body, "pull_request")
    )
    dup = await client.post(
        "/api/webhooks/github", content=body, headers=gh_headers(body, "pull_request")
    )
    assert first.status_code == 202 and first.json() == {"status": "queued"}
    assert dup.status_code == 200 and dup.json() == {"status": "duplicate"}
    delivery = db.execute(select(WebhookDelivery)).scalar_one()
    assert delivery.delivery_id == "github:d-1" and delivery.event == "pull_request"
    assert delivery.action == "opened" and delivery.status == "received"
    [(name, args)] = app.state.queue.calls
    assert name == "events.process" and args[0] == str(delivery.id)
    assert isinstance(args[1], dict)
    assert args[1]["kind"] == "pr_opened" and args[1]["pr"]["number"] == 7


async def test_github_ping_is_ignored(client: httpx.AsyncClient, app: FastAPI, db: Session) -> None:
    body = fixture_bytes("github", "ping")
    resp = await client.post(
        "/api/webhooks/github", content=body, headers=gh_headers(body, "ping", "d-9")
    )
    assert resp.status_code == 200 and resp.json() == {"status": "ignored"}
    assert app.state.queue.calls == []
    assert db.execute(select(WebhookDelivery)).scalar_one().status == "ignored"


async def test_github_malformed_json_is_ignored(client: httpx.AsyncClient, app: FastAPI) -> None:
    body = b"not json"
    resp = await client.post(
        "/api/webhooks/github", content=body, headers=gh_headers(body, "pull_request", "d-x")
    )
    assert resp.status_code == 200 and resp.json() == {"status": "ignored"}
    assert app.state.queue.calls == []


async def test_gitlab_token_checked_against_repo_secret(
    client: httpx.AsyncClient, app: FastAPI, db: Session, crypto: Crypto
) -> None:
    org = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-acme")
    make_repo(
        db,
        org,
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme-group/api",
        webhook_secret="hooksecret",
        crypto=crypto,
    )
    body = fixture_bytes("gitlab", "merge_request.open")
    base = {
        "X-Gitlab-Event": "Merge Request Hook",
        "X-Gitlab-Event-UUID": "u-1",
        "Content-Type": "application/json",
    }
    bad = await client.post(
        "/api/webhooks/gitlab", content=body, headers=base | {"X-Gitlab-Token": "nope"}
    )
    assert bad.status_code == 401
    ok = await client.post(
        "/api/webhooks/gitlab", content=body, headers=base | {"X-Gitlab-Token": "hooksecret"}
    )
    assert ok.status_code == 202
    assert app.state.queue.calls[0][1][1]["kind"] == "pr_opened"
    dup = await client.post(
        "/api/webhooks/gitlab", content=body, headers=base | {"X-Gitlab-Token": "hooksecret"}
    )
    assert dup.json() == {"status": "duplicate"}
    delivery = db.execute(select(WebhookDelivery)).scalar_one()
    assert delivery.delivery_id == "gitlab:u-1" and delivery.action == "open"


async def test_gitlab_idempotency_key_preferred(
    client: httpx.AsyncClient, db: Session, crypto: Crypto
) -> None:
    org = make_org(db, provider="gitlab", provider_org_id="10", slug="gl-acme")
    make_repo(
        db,
        org,
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme-group/api",
        webhook_secret="hooksecret",
        crypto=crypto,
    )
    body = fixture_bytes("gitlab", "merge_request.open")
    headers = {
        "X-Gitlab-Event": "Merge Request Hook",
        "X-Gitlab-Token": "hooksecret",
        "Idempotency-Key": "idem-1",
        "X-Gitlab-Event-UUID": "u-2",
    }
    assert (
        await client.post("/api/webhooks/gitlab", content=body, headers=headers)
    ).status_code == 202
    retry = headers | {"X-Gitlab-Event-UUID": "u-3"}  # GitLab retries keep Idempotency-Key
    assert (await client.post("/api/webhooks/gitlab", content=body, headers=retry)).json() == {
        "status": "duplicate"
    }
    assert db.execute(select(WebhookDelivery)).scalar_one().delivery_id == "gitlab:idem-1"


async def test_gitlab_unknown_project_is_401(client: httpx.AsyncClient) -> None:
    body = fixture_bytes("gitlab", "merge_request.open")
    resp = await client.post(
        "/api/webhooks/gitlab",
        content=body,
        headers={"X-Gitlab-Event": "Merge Request Hook", "X-Gitlab-Token": "x"},
    )
    assert resp.status_code == 401


async def test_razorpay_payment_captured_fulfills_once(
    client: httpx.AsyncClient, db: Session
) -> None:
    org = make_org(db, balance="3")
    db.add(
        Payment(
            org_id=org.id,
            razorpay_order_id="order_ABC",
            amount_paise=4900,
            credits=Decimal("5"),
            status="created",
        )
    )
    db.commit()
    body = fixture_bytes("razorpay", "payment.captured")
    headers = {
        "X-Razorpay-Signature": sign_razorpay("rzp-webhook-secret", body),
        "x-razorpay-event-id": "evt_1",
        "Content-Type": "application/json",
    }
    first = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    dup = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    assert first.json() == {"status": "processed"} and dup.json() == {"status": "duplicate"}
    db.expire_all()
    assert db.execute(select(Organization)).scalar_one().credits_balance == Decimal("8.00")
    assert db.execute(select(WebhookDelivery)).scalar_one().status == "processed"
    # A distinct event for the same order (order.paid after payment.captured) credits nothing.
    again = await client.post(
        "/api/webhooks/razorpay", content=body, headers=headers | {"x-razorpay-event-id": "evt_3"}
    )
    assert again.json() == {"status": "processed"}
    db.expire_all()
    assert db.execute(select(Organization)).scalar_one().credits_balance == Decimal("8.00")
    bad = await client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers=headers | {"X-Razorpay-Signature": "bad", "x-razorpay-event-id": "evt_2"},
    )
    assert bad.status_code == 401


async def test_razorpay_other_event_ignored(client: httpx.AsyncClient) -> None:
    body = b'{"event":"payment.failed","payload":{}}'
    headers = {"X-Razorpay-Signature": sign_razorpay("rzp-webhook-secret", body)}
    resp = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    assert resp.status_code == 200 and resp.json() == {"status": "ignored"}


class DownQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.down = True

    def enqueue(self, task_name: str, *args: object) -> None:
        if self.down:
            raise ConnectionError("broker down")
        self.calls.append((task_name, args))


async def test_enqueue_failure_lets_the_provider_retry(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    queue = DownQueue()
    app.state.queue = queue
    body = fixture_bytes("github", "pull_request.opened")
    first = await client.post(
        "/api/webhooks/github", content=body, headers=gh_headers(body, "pull_request")
    )
    assert first.status_code == 503
    assert db.execute(select(WebhookDelivery)).first() is None
    queue.down = False
    retry = await client.post(
        "/api/webhooks/github", content=body, headers=gh_headers(body, "pull_request")
    )
    assert retry.status_code == 202 and retry.json() == {"status": "queued"}
    assert [c[0] for c in queue.calls] == ["events.process"]


async def test_razorpay_fulfill_failure_is_not_deduplicated(
    client: httpx.AsyncClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.webhooks as webhooks_mod

    org = make_org(db, balance="3")
    db.add(
        Payment(
            org_id=org.id,
            razorpay_order_id="order_ABC",
            amount_paise=4900,
            credits=Decimal("5"),
            status="created",
        )
    )
    db.commit()
    real = webhooks_mod.fulfill

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(webhooks_mod, "fulfill", boom)
    body = fixture_bytes("razorpay", "payment.captured")
    headers = {
        "X-Razorpay-Signature": sign_razorpay("rzp-webhook-secret", body),
        "x-razorpay-event-id": "evt_1",
        "Content-Type": "application/json",
    }
    failed = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    assert failed.status_code >= 500
    db.expire_all()
    assert db.execute(select(WebhookDelivery)).first() is None
    monkeypatch.setattr(webhooks_mod, "fulfill", real)
    retry = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    assert retry.json() == {"status": "processed"}
    db.expire_all()
    assert db.execute(select(Organization)).scalar_one().credits_balance == Decimal("8.00")
