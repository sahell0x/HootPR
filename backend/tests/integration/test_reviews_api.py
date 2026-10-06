from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.models import (
    AgentStep,
    Finding,
    Identity,
    LlmCall,
    Organization,
    Review,
    ReviewTask,
    ToolRun,
    User,
)
from tests.factories import make_installation, make_member, make_org, make_pr, make_repo, make_user
from tests.helpers import login_as

pytestmark = pytest.mark.integration


def make_platform_owner(
    db: Session, app: FastAPI, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(Identity(user_id=user.id, provider="github", provider_user_id="501", username="alice"))
    db.commit()
    monkeypatch.setattr(app.state.settings, "platform_owners", "gitlab:bob, github:Alice")


async def test_list_and_detail(
    client: httpx.AsyncClient, app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = make_org(db)
    repo = make_repo(db, org, make_installation(db, org))
    pr = make_pr(db, repo)
    base = datetime(2026, 9, 1, tzinfo=UTC)
    reviews = []
    for i in range(3):
        r = Review(
            pr_id=pr.id,
            org_id=org.id,
            trigger="auto",
            status="completed",
            head_sha=f"{i}" * 40,
            credits_charged=Decimal("1"),
            files_considered=2,
            created_at=base + timedelta(minutes=i),
            input_tokens=100,
            output_tokens=20,
            cost_usd=Decimal("0.0001"),
        )
        db.add(r)
        reviews.append(r)
    db.flush()
    call = LlmCall(
        org_id=org.id,
        review_id=reviews[2].id,
        role="cheap",
        model="gpt-5-nano",
        provider_host="api.openai.com",
        input_tokens=10,
        cached_tokens=0,
        output_tokens=5,
        cost_usd=Decimal("0.000003"),
        latency_ms=120,
        status="ok",
    )
    db.add(call)
    db.commit()
    user = make_user(db)
    make_member(db, user, org, role="member")
    await login_as(client, app, user.id)

    page = (await client.get("/api/orgs/acme/reviews", params={"limit": 2})).json()
    assert [r["id"] for r in page["reviews"]] == [str(reviews[2].id), str(reviews[1].id)]
    first = page["reviews"][0]
    assert first["repo_full_name"] == "acme/web" and first["pr_number"] == 7
    assert first["credits_charged"] == "1" and first["status"] == "completed"
    assert page["next_before"] is not None
    rest = (
        await client.get(
            "/api/orgs/acme/reviews", params={"limit": 2, "before": page["next_before"]}
        )
    ).json()
    assert [r["id"] for r in rest["reviews"]] == [str(reviews[0].id)] and rest[
        "next_before"
    ] is None

    # tokens / LLM cost / models are internal: a regular member only ever sees credits
    assert first["cost_usd"] is None and first["input_tokens"] is None
    assert first["output_tokens"] is None
    detail = (await client.get(f"/api/orgs/acme/reviews/{reviews[2].id}")).json()
    assert detail["head_sha"] == "2" * 40 and detail["findings"] == []
    assert detail["trace"]["llm_calls"] == [] and detail["cost_usd"] is None
    assert "gpt-5-nano" not in str(detail)
    hidden = await client.get(f"/api/orgs/acme/reviews/{reviews[2].id}/llm-calls/{call.id}")
    assert hidden.status_code == 404

    make_platform_owner(db, app, user, monkeypatch)
    page = (await client.get("/api/orgs/acme/reviews", params={"limit": 2})).json()
    assert page["reviews"][0]["cost_usd"] == "0.000100"
    assert page["reviews"][0]["input_tokens"] == 100
    detail = (await client.get(f"/api/orgs/acme/reviews/{reviews[2].id}")).json()
    assert detail["trace"]["llm_calls"][0]["model"] == "gpt-5-nano"
    assert detail["trace"]["llm_calls"][0]["cost_usd"] == "0.000003"


async def test_review_of_other_org_is_404(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    mine = make_org(db)
    other = make_org(db, slug="other", provider_org_id="2")
    repo = make_repo(db, other, provider_repo_id="77", full_name="other/x")
    r = Review(
        pr_id=make_pr(db, repo).id,
        org_id=other.id,
        trigger="auto",
        status="completed",
        head_sha="x",
    )
    db.add(r)
    db.commit()
    user = make_user(db)
    make_member(db, user, mine)
    await login_as(client, app, user.id)
    assert (await client.get(f"/api/orgs/acme/reviews/{r.id}")).status_code == 404


async def test_filter_by_repo_and_limit_validation(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    org = make_org(db)
    inst = make_installation(db, org)
    web = make_repo(db, org, inst)
    api = make_repo(db, org, inst, provider_repo_id="1002", full_name="acme/api")
    for repo in (web, api):
        db.add(
            Review(
                pr_id=make_pr(db, repo).id,
                org_id=org.id,
                trigger="auto",
                status="skipped",
                skip_reason="draft",
                head_sha="x" * 40,
            )
        )
    db.commit()
    user = make_user(db)
    make_member(db, user, org, role="member")
    await login_as(client, app, user.id)
    page = (await client.get("/api/orgs/acme/reviews", params={"repo_id": str(api.id)})).json()
    assert [r["repo_full_name"] for r in page["reviews"]] == ["acme/api"]
    assert page["reviews"][0]["skip_reason"] == "draft" and page["reviews"][0]["cost_usd"] is None
    assert page["next_before"] is None
    assert (await client.get("/api/orgs/acme/reviews", params={"limit": 101})).status_code == 422


async def test_reviews_require_membership(
    client: httpx.AsyncClient, app: FastAPI, db: Session
) -> None:
    make_org(db)
    user = make_user(db)
    await login_as(client, app, user.id)
    assert (await client.get("/api/orgs/acme/reviews")).status_code in (403, 404)


@pytest.fixture
async def seeded_review(
    client: httpx.AsyncClient, app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> tuple[Review, Organization, User]:
    org = make_org(db)
    repo = make_repo(db, org, make_installation(db, org))
    pr = make_pr(db, repo)
    review = Review(
        pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha=pr.head_sha
    )
    db.add(review)
    db.commit()
    user = make_user(db)
    make_member(db, user, org, role="admin")
    make_platform_owner(db, app, user, monkeypatch)  # the trace tests inspect LLM calls
    await login_as(client, app, user.id)
    return review, org, user


async def test_review_detail_exposes_phase2_trace(
    client: httpx.AsyncClient, db: Session, seeded_review: tuple[Review, Organization, User]
) -> None:
    review, org, _user = seeded_review
    task = ReviewTask(
        review_id=review.id,
        ordinal=0,
        title="Auth checks",
        rationale="r",
        files=["a.py"],
        focus=["security"],
        status="done",
        summary="looked",
    )
    db.add(task)
    db.flush()
    review.stages = [
        {
            "name": "diff",
            "status": "ok",
            "started_at": "2026-09-29T10:00:00+00:00",
            "duration_ms": 12,
            "detail": "3 files",
        },
        {"name": "bogus-stage", "status": "ok"},  # malformed rows are skipped, never a 500
    ]
    review.files_reviewed = 1
    db.add_all(
        [
            Finding(
                review_id=review.id,
                path="a.py",
                end_line=40,
                severity="minor",
                category="style",
                title="Far away",
                body="b",
                confidence=0.4,
                judge_verdict="drop",
                judge_reason="outside_changed_hunk",
                fingerprint="g" * 32,
            ),
            Finding(
                review_id=review.id,
                task_id=task.id,
                path="a.py",
                start_line=3,
                end_line=4,
                severity="major",
                category="security",
                title="SQL injection",
                body="b",
                suggestion="safe()",
                source="llm",
                confidence=0.9,
                judge_verdict="keep",
                judge_reason="verified",
                posted=True,
                fingerprint="f" * 32,
                evidence=["rg output"],
            ),
            LlmCall(
                org_id=org.id,
                review_id=review.id,
                task_id=task.id,
                role="review",
                model="m",
                provider_host="h",
                status="error",
                error="boom",
                request_excerpt="REQ",
                response_excerpt="RESP",
            ),
            AgentStep(
                review_id=review.id,
                task_id=task.id,
                step_no=1,
                kind="tool_call",
                tool_name="shell",
                args={"cmd": "rg foo"},
            ),
            ToolRun(review_id=review.id, tool="ruff", status="failed", stderr_excerpt="oops"),
        ]
    )
    db.commit()
    r = await client.get(f"/api/orgs/acme/reviews/{review.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["files_reviewed"] == 1
    posted, dropped = body["findings"]
    assert posted["judge_verdict"] == "keep" and posted["suggestion"] == "safe()"
    assert posted["task_id"] == str(task.id) and posted["evidence"] == ["rg output"]
    assert posted["side"] == "RIGHT" and posted["fingerprint"] == "f" * 32
    assert dropped["judge_reason"] == "outside_changed_hunk" and dropped["posted"] is False
    assert dropped["task_id"] is None
    trace = body["trace"]
    assert [s["name"] for s in trace["stages"]] == ["diff"]
    assert trace["stages"][0]["duration_ms"] == 12 and trace["stages"][0]["detail"] == "3 files"
    assert trace["tasks"][0] == {
        "id": str(task.id),
        "ordinal": 0,
        "title": "Auth checks",
        "rationale": "r",
        "files": ["a.py"],
        "focus": ["security"],
        "status": "done",
        "summary": "looked",
    }
    assert trace["llm_calls"][0]["error"] == "boom"
    assert trace["llm_calls"][0]["task_id"] == str(task.id)
    assert "request_excerpt" not in trace["llm_calls"][0]
    assert trace["agent_steps"][0]["args"] == {"cmd": "rg foo"}
    assert trace["agent_steps"][0]["task_id"] == str(task.id)
    assert trace["agent_steps"][0]["created_at"]
    assert trace["tool_runs"][0]["stderr_excerpt"] == "oops"


async def test_findings_are_ordered_posted_then_severity(
    client: httpx.AsyncClient, db: Session, seeded_review: tuple[Review, Organization, User]
) -> None:
    review, _org, _user = seeded_review

    def f(sev: str, path: str, line: int, posted: bool) -> Finding:
        return Finding(
            review_id=review.id,
            path=path,
            end_line=line,
            severity=sev,
            category="bug",
            title=f"{sev}-{path}-{line}",
            body="b",
            posted=posted,
            fingerprint=f"{sev}{path}{line}",
        )

    db.add_all(
        [
            f("nitpick", "a.py", 1, True),
            f("critical", "z.py", 9, False),
            f("major", "b.py", 5, True),
            f("major", "a.py", 7, True),
            f("minor", "a.py", 2, True),
        ]
    )
    db.commit()
    body = (await client.get(f"/api/orgs/acme/reviews/{review.id}")).json()
    assert [x["title"] for x in body["findings"]] == [
        "major-a.py-7",
        "major-b.py-5",
        "minor-a.py-2",
        "nitpick-a.py-1",
        "critical-z.py-9",
    ]


async def test_llm_call_detail_returns_excerpts_and_is_org_scoped(
    client: httpx.AsyncClient, db: Session, seeded_review: tuple[Review, Organization, User]
) -> None:
    review, org, _user = seeded_review
    call = LlmCall(
        org_id=org.id,
        review_id=review.id,
        role="cheap",
        model="m",
        provider_host="h",
        status="ok",
        request_excerpt="REQ",
        response_excerpt="RESP",
    )
    db.add(call)
    db.commit()
    r = await client.get(f"/api/orgs/acme/reviews/{review.id}/llm-calls/{call.id}")
    assert r.status_code == 200
    assert r.json()["request_excerpt"] == "REQ" and r.json()["response_excerpt"] == "RESP"
    assert r.json()["role"] == "cheap"
    other = await client.get(f"/api/orgs/acme/reviews/{review.id}/llm-calls/{review.id}")
    assert other.status_code == 404
    assert other.json()["detail"]["code"] == "not_found"


async def test_llm_call_detail_of_other_org_review_is_404(
    client: httpx.AsyncClient, db: Session, seeded_review: tuple[Review, Organization, User]
) -> None:
    _review, _org, _user = seeded_review
    other = make_org(db, slug="other", provider_org_id="2")
    repo = make_repo(db, other, provider_repo_id="77", full_name="other/x")
    foreign = Review(
        pr_id=make_pr(db, repo).id,
        org_id=other.id,
        trigger="auto",
        status="completed",
        head_sha="x",
    )
    db.add(foreign)
    db.flush()
    call = LlmCall(
        org_id=other.id,
        review_id=foreign.id,
        role="cheap",
        model="m",
        provider_host="h",
        status="ok",
        request_excerpt="SECRET",
    )
    db.add(call)
    db.commit()
    r = await client.get(f"/api/orgs/acme/reviews/{foreign.id}/llm-calls/{call.id}")
    assert r.status_code == 404


async def test_credit_receipt_and_billing_metering(
    client: httpx.AsyncClient, app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.billing.ledger import CreditLedger, Reservation

    org = make_org(db, balance="1000")
    pr = make_pr(db, make_repo(db, org, make_installation(db, org)))
    review = Review(
        pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="a" * 40,
        degraded={"credit_budget": "reached"}, finished_at=datetime.now(UTC),
    )  # fmt: skip
    skipped = Review(
        pr_id=pr.id, org_id=org.id, trigger="auto", status="skipped", head_sha="b" * 40
    )
    db.add_all([review, skipped])
    db.flush()
    for stage, credits, tokens in (
        ("summarize", "40.000000", 900),
        ("agents", "210.000000", 5000),
        ("agents", "34.100000", 800),
        (None, "0.000000", 0),
    ):
        db.add(
            LlmCall(
                org_id=org.id, review_id=review.id, role="review", model="gpt-6-luna",
                provider_host="api.openai.com", input_tokens=tokens, cached_tokens=10,
                output_tokens=7, cost_usd=Decimal("0.001"), latency_ms=5, status="ok",
                stage=stage, credits=Decimal(credits),
            )
        )  # fmt: skip
    ledger = CreditLedger()
    hold = ledger.reserve_up_to(db, org.id, Decimal("600"), Decimal("10"), "review", review.id)
    assert isinstance(hold, Reservation)
    review.credits_charged = ledger.settle(db, hold, Decimal("284.1"), Decimal("10"))
    db.commit()
    user = make_user(db)
    make_member(db, user, org, role="member")
    await login_as(client, app, user.id)

    detail = (await client.get(f"/api/orgs/acme/reviews/{review.id}")).json()
    receipt = detail["receipt"]
    assert {k: receipt[k] for k in ("reserved", "charged", "refunded")} == {
        "reserved": "600",
        "charged": "285",
        "refunded": "315",
    }
    assert receipt["minimum_applied"] is False and receipt["budget_reached"] is True
    assert [(x["stage"], x["label"], x["credits"]) for x in receipt["lines"]] == [
        # whole credits that add up to the charge (metered 284.1 -> charged 285)
        ("agents", "Review agents", "245"),
        ("summarize", "Walkthrough", "40"),
        ("other", "Other", "0"),
    ]
    line = receipt["lines"][0]
    assert line["input_tokens"] is None and line["cost_usd"] is None  # owner-only
    assert (await client.get(f"/api/orgs/acme/reviews/{skipped.id}")).json()["receipt"] is None

    bill = (await client.get("/api/orgs/acme/billing")).json()
    assert bill["metering"] == {
        "review_min_charge": "10",
        "review_hold_max": "1000",
        "chat_min_charge": "5",
        "avg_review_credits_30d": "285",
        "reviews_30d": 1,
    }
    settle_row = bill["ledger"][0]
    assert (settle_row["reason"], settle_row["delta"], settle_row["charged"]) == (
        "review",
        "315",
        "285",
    )
    assert all(e["charged"] is None for e in bill["ledger"][1:])

    make_platform_owner(db, app, user, monkeypatch)
    detail = (await client.get(f"/api/orgs/acme/reviews/{review.id}")).json()
    line = detail["receipt"]["lines"][0]
    assert line["input_tokens"] == 5800 and line["output_tokens"] == 14
    assert line["cost_usd"] == "0.002000"
