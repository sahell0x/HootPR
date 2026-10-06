"""Phase 1 'Done when' (spec §16), driven end to end with the real platform clients against
respx-mocked provider APIs: webhook → worker → walkthrough (review engine with the fake sandbox
and LLM) + status + token-metered credits (hold → settle at the minimum charge with the fake LLM)
on GitHub and GitLab; the rate-limit and out-of-credit comments; Razorpay test-mode pack
purchases (+1 pack each) and the purchase/balance caps."""

import hashlib
import hmac
import json
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import Crypto
from app.events.processing import process_delivery
from app.models import Organization
from app.platforms.factory import make_platform_factory
from app.review.pipeline import run_review
from app.settings import Settings
from app.worker.context import WorkerContext
from tests.factories import make_installation, make_member, make_org, make_repo, make_user
from tests.fakes.kv import DictKV
from tests.fixtures import fixture_bytes, sign_github, sign_razorpay
from tests.helpers import login_as

pytestmark = pytest.mark.integration
GH = "https://api.github.com/repos/acme/web"
GL = "https://gitlab.com/api/v4/projects/2002"


def drain(app: FastAPI, ctx: WorkerContext) -> None:
    for name, args in app.state.queue.calls:
        assert name == "events.process"
        process_delivery(ctx, str(args[0]), args[1])  # type: ignore[arg-type]
    for name, args in list(ctx.queue.calls):  # type: ignore[attr-defined]
        if name == "review.run":
            run_review(ctx, UUID(str(args[0])))


def org_balance(db: Session) -> Decimal:
    db.expire_all()
    return db.execute(select(Organization)).scalar_one().credits_balance


async def test_github_pr_gets_walkthrough_and_is_charged_metered_credits(
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    org = make_org(db, balance="300")
    make_repo(db, org, make_installation(db, org))
    body = fixture_bytes("github", "pull_request.opened")
    resp = await client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "e2e-1",
            "X-Hub-Signature-256": sign_github("gh-webhook-secret", body),
        },
    )
    assert resp.status_code == 202
    ctx = make_wctx(
        platforms=make_platform_factory(
            int_settings, DictKV({"gh:insttoken:42": "ghs_e2e"}), crypto
        )
    )
    pr_json = json.loads(body)["pull_request"]
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{GH}/pulls/7").mock(return_value=httpx.Response(200, json=pr_json))
        mock.get(f"{GH}/contents/.hootpr.yaml").mock(return_value=httpx.Response(404))
        checks = mock.post(f"{GH}/check-runs").mock(
            return_value=httpx.Response(201, json={"id": 1})
        )
        mock.get(f"{GH}/pulls/7/files").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "filename": "src/login.py",
                        "status": "modified",
                        "additions": 2,
                        "deletions": 1,
                        "patch": "@@ -1 +1,2 @@\n-a\n+b\n+c",
                    }
                ],
            )
        )
        mock.get(f"{GH}/issues/7/comments").mock(return_value=httpx.Response(200, json=[]))
        posted = mock.post(f"{GH}/issues/7/comments").mock(
            return_value=httpx.Response(201, json={"id": 11})
        )
        described = mock.patch(f"{GH}/pulls/7").mock(return_value=httpx.Response(200, json=pr_json))
        drain(app, ctx)
    edits = [json.loads(c.request.content) for c in described.calls]
    assert any("hootpr:summary:start" in e.get("body", "") for e in edits)
    comment = json.loads(posted.calls[0].request.content)["body"]
    assert comment.startswith("<!-- hootpr:walkthrough -->") and "src/login.py" in comment
    runs = [json.loads(c.request.content) for c in checks.calls]
    assert [(r["name"], r["status"], r.get("conclusion")) for r in runs] == [
        ("HootPR", "in_progress", None),
        ("HootPR", "completed", "success"),
    ]
    # Metered: the hold is settled at the fake LLM's usage, i.e. the minimum charge.
    assert org_balance(db) == Decimal("300") - int_settings.review_min_charge


async def test_gitlab_mr_gets_walkthrough_and_is_charged_metered_credits(
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    org = make_org(
        db,
        provider="gitlab",
        provider_org_id="10",
        slug="gl-acme-group",
        kind="group",
        balance="300",
    )
    inst = make_installation(
        db, org, github_installation_id=None, gitlab_token="glpat-bot", crypto=crypto
    )
    make_repo(
        db,
        org,
        inst,
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme-group/api",
        webhook_secret="hooksecret",
        crypto=crypto,
    )
    body = fixture_bytes("gitlab", "merge_request.open")
    resp = await client.post(
        "/api/webhooks/gitlab",
        content=body,
        headers={
            "X-Gitlab-Event": "Merge Request Hook",
            "X-Gitlab-Token": "hooksecret",
            "X-Gitlab-Event-UUID": "e2e-2",
        },
    )
    assert resp.status_code == 202
    ctx = make_wctx(platforms=make_platform_factory(int_settings, DictKV(), crypto))
    head = "a" * 40
    mr = {
        "iid": 3,
        "title": "Fix pagination",
        "description": "Closes #1",
        "state": "opened",
        "draft": False,
        "source_branch": "fix/pagination",
        "target_branch": "main",
        "sha": head,
        "web_url": "https://gitlab.com/acme-group/api/-/merge_requests/3",
        "author": {"username": "carol"},
        "labels": [],
        "diff_refs": {"base_sha": "b" * 40, "head_sha": head, "start_sha": "b" * 40},
    }
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{GL}/merge_requests/3").mock(return_value=httpx.Response(200, json=mr))
        mock.get(f"{GL}/repository/files/.hootpr.yaml/raw").mock(return_value=httpx.Response(404))
        statuses = mock.post(f"{GL}/statuses/{head}").mock(
            return_value=httpx.Response(201, json={})
        )
        mock.get(f"{GL}/merge_requests/3/diffs").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "new_path": "api/pages.py",
                        "old_path": "api/pages.py",
                        "diff": "@@ -1 +1 @@\n-a\n+b\n",
                        "new_file": False,
                        "renamed_file": False,
                        "deleted_file": False,
                    }
                ],
            )
        )
        mock.get(f"{GL}/merge_requests/3/notes").mock(return_value=httpx.Response(200, json=[]))
        note = mock.post(f"{GL}/merge_requests/3/notes").mock(
            return_value=httpx.Response(201, json={"id": 5})
        )
        described = mock.put(f"{GL}/merge_requests/3").mock(
            return_value=httpx.Response(200, json=mr)
        )
        mock.get(f"{GL}/issues/1").mock(
            return_value=httpx.Response(
                200, json={"iid": 1, "title": "Pagination", "description": "", "state": "opened"}
            )
        )
        drain(app, ctx)
    edits = [json.loads(c.request.content) for c in described.calls]
    assert any("hootpr:summary:start" in e.get("description", "") for e in edits)
    assert "api/pages.py" in json.loads(note.calls[0].request.content)["body"]
    assert [json.loads(c.request.content)["state"] for c in statuses.calls] == [
        "running",
        "success",
    ]
    # Metered: the hold is settled at the fake LLM's usage, i.e. the minimum charge.
    assert org_balance(db) == Decimal("300") - int_settings.review_min_charge


# --- rate-limit and out-of-credit paths (spec §16: "post the right comment") -----------------


def mock_github_pr(mock: respx.MockRouter, pr_json: dict[str, object]) -> dict[str, respx.Route]:
    mock.get(f"{GH}/pulls/7").mock(return_value=httpx.Response(200, json=pr_json))
    mock.get(f"{GH}/contents/.hootpr.yaml").mock(return_value=httpx.Response(404))
    mock.get(f"{GH}/pulls/7/files").mock(return_value=httpx.Response(200, json=[]))
    mock.get(f"{GH}/issues/7/comments").mock(return_value=httpx.Response(200, json=[]))
    return {
        "checks": mock.post(f"{GH}/check-runs").mock(
            return_value=httpx.Response(201, json={"id": 1})
        ),
        "comment": mock.post(f"{GH}/issues/7/comments").mock(
            return_value=httpx.Response(201, json={"id": 11})
        ),
    }


async def post_github_pr_opened(client: httpx.AsyncClient, delivery: str) -> bytes:
    body = fixture_bytes("github", "pull_request.opened")
    resp = await client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": sign_github("gh-webhook-secret", body),
        },
    )
    assert resp.status_code == 202
    return body


async def test_github_rate_limited_pr_gets_rate_limit_comment_and_no_charge(
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    org = make_org(db, balance="500")
    make_repo(db, org, make_installation(db, org))
    ctx = make_wctx(
        platforms=make_platform_factory(
            int_settings, DictKV({"gh:insttoken:42": "ghs_e2e"}), crypto
        )
    )
    for _ in range(int_settings.rate_limit_reviews_per_hour):  # the hour's allowance is used up
        ctx.limiter.check_and_consume(org.id, "review")
    body = await post_github_pr_opened(client, "e2e-rl")
    with respx.mock(assert_all_called=False) as mock:
        routes = mock_github_pr(mock, json.loads(body)["pull_request"])
        drain(app, ctx)
    comment = json.loads(routes["comment"].calls[-1].request.content)["body"]
    assert comment.startswith("<!-- hootpr:walkthrough -->")
    assert "## Review rate limited" in comment and "@hootpr review" in comment
    last = json.loads(routes["checks"].calls[-1].request.content)
    assert (last["status"], last["conclusion"]) == ("completed", "success")
    assert last["output"]["title"] == "Review rate limited"
    assert org_balance(db) == Decimal("500")  # a rate-limited review costs nothing


async def test_gitlab_mr_without_credits_gets_out_of_credits_note(
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    org = make_org(
        db, provider="gitlab", provider_org_id="10", slug="gl-acme-group", kind="group", balance="0"
    )
    inst = make_installation(
        db, org, github_installation_id=None, gitlab_token="glpat-bot", crypto=crypto
    )
    make_repo(
        db,
        org,
        inst,
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme-group/api",
        webhook_secret="hooksecret",
        crypto=crypto,
    )
    body = fixture_bytes("gitlab", "merge_request.open")
    resp = await client.post(
        "/api/webhooks/gitlab",
        content=body,
        headers={
            "X-Gitlab-Event": "Merge Request Hook",
            "X-Gitlab-Token": "hooksecret",
            "X-Gitlab-Event-UUID": "e2e-noc",
        },
    )
    assert resp.status_code == 202
    ctx = make_wctx(platforms=make_platform_factory(int_settings, DictKV(), crypto))
    head = "a" * 40
    mr = {
        "iid": 3,
        "title": "Fix pagination",
        "description": "",
        "state": "opened",
        "draft": False,
        "source_branch": "fix/pagination",
        "target_branch": "main",
        "sha": head,
        "web_url": "https://gitlab.com/acme-group/api/-/merge_requests/3",
        "author": {"username": "carol"},
        "labels": [],
        "diff_refs": {"base_sha": "b" * 40, "head_sha": head, "start_sha": "b" * 40},
    }
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{GL}/merge_requests/3").mock(return_value=httpx.Response(200, json=mr))
        mock.get(f"{GL}/repository/files/.hootpr.yaml/raw").mock(return_value=httpx.Response(404))
        mock.get(f"{GL}/merge_requests/3/notes").mock(return_value=httpx.Response(200, json=[]))
        statuses = mock.post(url__regex=rf"{GL}/statuses/[0-9a-f]{{40}}").mock(
            return_value=httpx.Response(201, json={})
        )
        note = mock.post(f"{GL}/merge_requests/3/notes").mock(
            return_value=httpx.Response(201, json={"id": 5})
        )
        drain(app, ctx)
    assert ctx.queue.calls == []  # type: ignore[attr-defined]  # no review job was queued
    text = json.loads(note.calls[-1].request.content)["body"]
    assert "## Out of credits" in text and "/o/gl-acme-group/billing" in text
    assert "Reviews are metered by AI usage" in text
    assert f"at least {int_settings.review_min_charge:,} to start" in text
    # The test-mode payment disclaimer is shown only where a user is about to pay.
    assert "no real money" not in text
    last = json.loads(statuses.calls[-1].request.content)
    assert last["state"] == "success" and last["description"] == "Out of credits"
    assert org_balance(db) == Decimal("0")


# --- Razorpay test-mode pack purchase + caps (spec §16) -------------------------------------


def rzp_sig(order_id: str, payment_id: str) -> str:
    msg = f"{order_id}|{payment_id}".encode()
    return hmac.new(b"rzp-secret", msg, hashlib.sha256).hexdigest()


async def create_order(client: httpx.AsyncClient, order_id: str) -> httpx.Response:
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.post("https://api.razorpay.com/v1/orders").mock(
            return_value=httpx.Response(
                200, json={"id": order_id, "amount": 4900, "currency": "INR", "status": "created"}
            )
        )
        return await client.post("/api/orgs/acme/billing/orders")


async def test_buying_packs_adds_a_pack_each_and_caps_are_enforced(
    client: httpx.AsyncClient, app: FastAPI, db: Session, int_settings: Settings
) -> None:
    org = make_org(db, balance="0")
    user = make_user(db)
    make_member(db, user, org, role="admin")
    await login_as(client, app, user.id)
    summary = (await client.get("/api/orgs/acme/billing")).json()
    assert summary["test_mode"] is True and "no real money" in summary["disclaimer"]

    pack = Decimal(int_settings.credit_pack_credits)
    assert 2 * pack == int_settings.max_credit_balance  # two packs reach the balance cap

    # Pack 1: Checkout handler → signature verified → +1 pack.
    first = await create_order(client, "order_E2E1")
    assert first.status_code == 201
    verify = await client.post(
        "/api/billing/verify",
        json={
            "razorpay_order_id": "order_E2E1",
            "razorpay_payment_id": "pay_E2E1",
            "razorpay_signature": rzp_sig("order_E2E1", "pay_E2E1"),
        },
    )
    assert verify.json() == {"status": "paid", "credits_added": f"{pack}", "balance": f"{pack}"}

    # Pack 2: fulfilled by the payment.captured webhook instead of the browser → +1 pack.
    assert (await create_order(client, "order_E2E2")).status_code == 201
    event = json.loads(fixture_bytes("razorpay", "payment.captured"))
    event["payload"]["payment"]["entity"].update(order_id="order_E2E2", id="pay_E2E2")
    raw = json.dumps(event).encode()
    hook = await client.post(
        "/api/webhooks/razorpay",
        content=raw,
        headers={
            "X-Razorpay-Signature": sign_razorpay("rzp-webhook-secret", raw),
            "x-razorpay-event-id": "evt_e2e2",
            "Content-Type": "application/json",
        },
    )
    assert hook.json() == {"status": "processed"}
    assert org_balance(db) == 2 * pack

    # Pack 3: both caps (2 purchases, max balance) now block the order.
    third = await create_order(client, "order_E2E3")
    assert third.status_code == 409 and third.json()["detail"]["code"] == "purchase_cap_reached"
    summary = (await client.get("/api/orgs/acme/billing")).json()
    assert summary["can_purchase"] is False and summary["balance"] == f"{2 * pack}"
    db.expire_all()
    fresh = db.execute(select(Organization)).scalar_one()
    fresh.purchases_count = 0  # isolate the balance cap
    db.commit()
    capped = await create_order(client, "order_E2E4")
    assert capped.status_code == 409 and capped.json()["detail"]["code"] == "balance_cap_exceeded"
