"""The Celery pipeline running the real engine (FakeSandbox + stage-aware fake LLM)."""

from collections.abc import Callable
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Finding, Organization, PullRequest, Review, ReviewTask, ToolRun
from app.platforms.base import PlatformError
from app.platforms.diff import build_file_diff
from app.platforms.local import LocalPlatform
from app.review.pipeline import handle_pr_event
from app.sandbox.base import SandboxUnavailable
from app.worker.context import WorkerContext
from tests.fakes.engine_llm import EngineFakeLLM
from tests.fakes.sandbox import FakeSandbox, FakeSandboxManager
from tests.integration.test_pipeline import REF, pr_event, run_queued, seed

pytestmark = pytest.mark.integration
MARK = "<!-- hootpr:walkthrough -->"
KEY = ("1001", 7)


def balance(db: Session) -> Decimal:
    db.expire_all()
    return db.execute(select(Organization)).scalar_one().credits_balance


def test_review_posts_findings_persists_trace_and_charges(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    seed(db, local_platform)
    engine_llm.findings = [
        {"path": "src/login.py", "end_line": 2, "severity": "major", "title": "Off by one"},
        {"path": "src/login.py", "end_line": 99, "title": "Nowhere"},
    ]
    tools = {
        "version": 1,
        "runs": [{"tool": "ruff", "status": "ok", "duration_ms": 5, "findings_count": 0,
                  "stderr_excerpt": ""}],
        "findings": [],
    }  # fmt: skip
    ctx = make_wctx(sandboxes=FakeSandboxManager(tools=tools))
    assert handle_pr_event(ctx, pr_event()) == "processed"
    run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert review.status == "completed" and review.findings_posted == 1
    assert review.files_reviewed == 1 and review.files_considered == 1
    assert review.input_tokens > 0 and review.credits_charged == Decimal("10")
    names = [s["name"] for s in review.stages]
    assert names[:2] == ["config", "diff"] and names[-2:] == ["post", "close"]
    assert "judge" in names and "agents" in names
    rows = {f.title: f for f in db.execute(select(Finding)).scalars()}
    assert rows["Off by one"].posted and rows["Off by one"].judge_verdict == "keep"
    assert rows["Off by one"].provider_comment_id and rows["Off by one"].fingerprint
    assert rows["Nowhere"].judge_verdict == "drop"
    assert rows["Nowhere"].judge_reason == "outside_changed_hunk" and not rows["Nowhere"].posted
    task = db.execute(select(ReviewTask)).scalar_one()
    assert task.status == "done" and rows["Off by one"].task_id == task.id
    assert db.execute(select(ToolRun)).scalar_one().tool == "ruff"
    assert local_platform.reviews[0].comments[0].end_line == 2
    assert local_platform.comments[KEY][0].body.startswith(MARK)
    assert "## Walkthrough" in local_platform.comments[KEY][0].body
    assert local_platform.statuses[-1].state == "success"
    pr = db.execute(select(PullRequest)).scalar_one()
    assert pr.last_reviewed_sha == review.head_sha and pr.reviewed_commits_count == 1
    assert pr.walkthrough_comment_id == local_platform.comments[KEY][0].id
    assert balance(db) == Decimal("290")
    sb: FakeSandbox = ctx.sandboxes.created[0]  # type: ignore[attr-defined]
    assert sb.sealed and sb.destroyed


def test_pr_with_only_lockfiles_is_skipped_and_refunded(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    local_platform.diffs[KEY] = [
        build_file_diff("pnpm-lock.yaml", "@@ -1 +1 @@\n-a\n+b\n", "modified")
    ]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert (review.status, review.skip_reason) == ("skipped", "no_reviewable_files")
    assert review.credits_charged == Decimal("0")
    assert balance(db) == Decimal("300") and ctx.sandboxes.created == []  # type: ignore[attr-defined]
    body = local_platform.comments[KEY][0].body
    assert "No reviewable files" in body and "pnpm-lock.yaml" in body
    assert (local_platform.statuses[-1].state, local_platform.statuses[-1].title) == (
        "neutral",
        "Skipped: no reviewable files (every changed file was excluded)",
    )
    pr = db.execute(select(PullRequest)).scalar_one()
    assert pr.last_reviewed_sha == review.head_sha


def test_missing_sandbox_image_fails_and_refunds(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    class Broken(FakeSandboxManager):
        def create(self, job_id: str, *, mem_mb: int, cpus: float) -> FakeSandbox:
            raise SandboxUnavailable(
                "sandbox image hootpr/sandbox:latest is missing — run `make sandbox-image`"
            )

    seed(db, local_platform)
    ctx = make_wctx(sandboxes=Broken())
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert review.status == "failed" and "make sandbox-image" in (review.error or "")
    assert balance(db) == Decimal("300") and local_platform.statuses[-1].state == "neutral"
    body = local_platform.comments[KEY][0].body
    assert "no credit was charged" in body and "sandbox is unavailable" in body


def test_llm_provider_down_fails_and_refunds(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    seed(db, local_platform)
    engine_llm.fail_500 = 99
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert review.status == "failed"
    assert (review.error or "").startswith("ProviderUnavailable")
    assert balance(db) == Decimal("300")
    assert "AI provider" in local_platform.comments[KEY][0].body
    failed = [s for s in review.stages if s["status"] == "failed"]
    assert failed and failed[0]["name"] == "triage"  # the trace shows how far it got


def test_request_changes_workflow_sets_failure_status(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    org = seed(db, local_platform)
    org.settings = {"reviews": {"request_changes_workflow": True}}
    db.commit()
    engine_llm.findings = [
        {"path": "src/login.py", "end_line": 2, "severity": "critical", "title": "Crash"}
    ]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    assert local_platform.reviews[0].event == "REQUEST_CHANGES"
    assert local_platform.statuses[-1].state == "failure"
    assert local_platform.statuses[-1].title == "Changes requested"
    db.expire_all()
    assert db.execute(select(PullRequest)).scalar_one().blocking_state == "changes_requested"


def test_prior_fingerprints_only_include_open_posted_findings(db: Session) -> None:
    from app.review.pipeline import _prior_fingerprints
    from tests.factories import make_installation, make_org, make_pr, make_repo

    org = make_org(db)
    pr = make_pr(db, make_repo(db, org, make_installation(db, org)))
    r = Review(pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="2" * 40)
    db.add(r)
    db.flush()
    for fp, posted, status in (
        ("open", True, "open"),
        ("res", True, "resolved"),
        ("np", False, "open"),
    ):
        db.add(
            Finding(review_id=r.id, path="a.py", end_line=1, severity="minor", category="bug",
                    title="t", body="b", posted=posted, status=status, fingerprint=fp)
        )  # fmt: skip
    db.commit()
    assert _prior_fingerprints(db, pr.id) == frozenset({"open"})


def test_posting_platform_error_fails_and_refunds(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    seed(db, local_platform)
    engine_llm.findings = [{"path": "src/login.py", "end_line": 2, "title": "X"}]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    local_platform.fail_next = PlatformError(502, "bad gateway")
    run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert review.status == "failed" and review.stages[-1]["name"] == "post"
    assert balance(db) == Decimal("300")


def test_second_review_does_not_repost_a_posted_finding(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    seed(db, local_platform)
    engine_llm.findings = [{"path": "src/login.py", "end_line": 2, "title": "X"}]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    ctx.queue.calls.clear()  # type: ignore[attr-defined]
    from tests.integration.test_pipeline import set_live_pr

    set_live_pr(local_platform, "3" * 40)
    handle_pr_event(ctx, pr_event("pull_request.synchronize", head="3" * 40))
    run_queued(ctx)
    db.expire_all()
    reviews = db.execute(select(Review).order_by(Review.created_at)).scalars().all()
    assert [r.status for r in reviews] == ["completed", "completed"]
    assert reviews[1].findings_posted == 0 and len(local_platform.reviews) == 1
    second = db.execute(select(Finding).where(Finding.review_id == reviews[1].id)).scalar_one()
    assert second.judge_reason == "already_posted"


class WorkerDied(BaseException):
    """Stands in for the worker process dying (never caught by `except Exception`)."""


def test_crash_after_posting_does_not_repost_on_retry(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §7.9: findings are written (pending) before posting; the acks_late retry reconciles
    them with the PR's comments instead of posting every inline comment again."""
    import app.review.pipeline as pipeline

    seed(db, local_platform)
    engine_llm.findings = [{"path": "src/login.py", "end_line": 2, "title": "Off by one"}]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    real = pipeline._persist_success

    def die(*a: object, **k: object) -> None:
        raise WorkerDied

    monkeypatch.setattr(pipeline, "_persist_success", die)
    with pytest.raises(WorkerDied):
        run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert review.status == "running" and len(local_platform.reviews) == 1
    pending = db.execute(select(Finding)).scalars().all()
    assert [(f.title, f.status, f.posted) for f in pending] == [("Off by one", "pending", False)]
    monkeypatch.setattr(pipeline, "_persist_success", real)
    run_queued(ctx)  # acks_late redelivery
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert review.status == "completed" and review.degraded.get("retried_after_crash") is True
    assert len(local_platform.reviews) == 1  # nothing posted twice
    [row] = db.execute(select(Finding)).scalars().all()
    assert row.judge_reason == "already_posted" and row.status == "open"
    names = [s["name"] for s in review.stages]
    assert names.count("diff") == 1 and names.count("post") == 1  # old attempt's trace dropped
    assert db.execute(select(ReviewTask)).scalars().all().__len__() == 1
    assert balance(db) == Decimal("290")


def test_crash_before_posting_retries_with_a_clean_trace(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    from app.models import AgentStep

    seed(db, local_platform)
    engine_llm.findings = [{"path": "src/login.py", "end_line": 2, "title": "Off by one"}]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    review = db.execute(select(Review)).scalar_one()
    review.status = "running"  # the worker died mid-review, after writing some trace
    review.stages = [{"name": "diff", "status": "ok", "started_at": "x", "duration_ms": 1}]
    stale = ReviewTask(review_id=review.id, ordinal=0, title="old", rationale="", files=[],
                       focus=[], related_symbols=[], status="running")  # fmt: skip
    db.add(stale)
    db.flush()
    db.add(AgentStep(review_id=review.id, task_id=stale.id, step_no=1, kind="tool_call", args={}))
    db.add(ToolRun(review_id=review.id, tool="ruff", status="ok", findings_count=0))
    db.commit()
    stale_id = stale.id
    run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    assert review.status == "completed"
    assert [s["name"] for s in review.stages].count("diff") == 1
    assert [t.title for t in db.execute(select(ReviewTask)).scalars()] not in ([], ["old"])
    assert "old" not in [t.title for t in db.execute(select(ReviewTask)).scalars()]
    steps = db.execute(select(AgentStep)).scalars().all()
    assert steps and all(st.task_id != stale_id for st in steps)
    assert sorted(st.step_no for st in steps) == list(range(1, len(steps) + 1))
    assert len(local_platform.reviews) == 1 and local_platform.reviews[0].comments


def test_failure_after_posting_charges_and_keeps_the_walkthrough(
    db: Session,
    local_platform: LocalPlatform,
    engine_llm: EngineFakeLLM,
    make_wctx: Callable[..., WorkerContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.review.pipeline as pipeline

    seed(db, local_platform)
    engine_llm.findings = [{"path": "src/login.py", "end_line": 2, "title": "Off by one"}]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(pipeline, "_persist_success", boom)
    run_queued(ctx)
    db.expire_all()
    review = db.execute(select(Review)).scalar_one()
    # delivered, so it settles at the metered credits (the fake LLM meters ~0 -> the minimum)
    assert review.status == "failed" and review.credits_charged == Decimal("10")
    assert balance(db) == Decimal("290")
    assert "## Walkthrough" in local_platform.comments[KEY][0].body


PRINT_NIT = {
    "path": "src/login.py",
    "end_line": 2,
    "severity": "minor",
    "title": "Avoid print debugging",
}
OFF_BY_ONE = {"path": "src/login.py", "end_line": 2, "severity": "major", "title": "Off by one"}


def _walkthrough(lp: LocalPlatform) -> str:
    return next(c.body for c in lp.comments[KEY] if c.body.startswith(MARK))


def test_learning_in_db_changes_the_review(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    engine_llm: EngineFakeLLM,
) -> None:
    from dataclasses import replace

    from app.models import Learning, Repository
    from tests.fakes.keyword_embed import keyword_vector

    org = seed(db, local_platform)
    live = local_platform.get_pull_request(REF, 7)
    diff = build_file_diff("src/login.py", "@@ -1 +1,2 @@\n-a\n+print(b)\n+c\n", "modified")
    local_platform.add_pull_request(REF, replace(live), [diff])
    repo = db.execute(select(Repository)).scalar_one()
    text = "We use print for CLI output here; do not flag print statements."
    db.add(
        Learning(
            org_id=org.id,
            repo_id=repo.id,
            scope="repo",
            text=text,
            embedding=keyword_vector(text),
            embedding_model=make_wctx().settings.llm_embed_model,
            created_by_username="bob",
        )
    )
    db.commit()
    engine_llm.embed_fn = keyword_vector
    engine_llm.findings = [OFF_BY_ONE, PRINT_NIT]
    engine_llm.suppress = {"Avoid print debugging": "print"}
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    db.expire_all()
    titles = {f.title for f in db.execute(select(Finding)).scalars()}
    assert titles == {"Off by one"}
    body = _walkthrough(local_platform)
    assert "- **🧠 Learnings used:** 1" in body and "We use print for CLI output" in body


def test_repo_opt_out_purges_repo_learnings_and_skips_retrieval(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    engine_llm: EngineFakeLLM,
) -> None:
    from app.models import Learning, Repository

    org = seed(db, local_platform)
    repo = db.execute(select(Repository)).scalar_one()
    repo.settings = {"knowledge_base": {"opt_out": True}}
    db.add(
        Learning(
            org_id=org.id, repo_id=repo.id, scope="repo", text="print ok", created_by_username="bob"
        )
    )
    db.commit()
    engine_llm.findings = [OFF_BY_ONE]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    db.expire_all()
    assert db.execute(select(Learning)).first() is None
    assert db.execute(select(Review)).scalar_one().status == "completed"
    assert not any(r["path"].endswith("/embeddings") for r in engine_llm.requests)


def test_org_opt_out_skips_retrieval(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    engine_llm: EngineFakeLLM,
) -> None:
    from app.models import Learning
    from tests.fakes.keyword_embed import keyword_vector

    org = seed(db, local_platform)
    org.knowledge_base_opt_out = True
    db.add(
        Learning(
            org_id=org.id,
            scope="org",
            text="print ok",
            embedding=keyword_vector("print ok"),
            embedding_model=make_wctx().settings.llm_embed_model,
            created_by_username="bob",
        )
    )
    db.commit()
    engine_llm.findings = [OFF_BY_ONE]
    ctx = make_wctx()
    handle_pr_event(ctx, pr_event())
    run_queued(ctx)
    assert not any(r["path"].endswith("/embeddings") for r in engine_llm.requests)
    assert "Learnings used" not in _walkthrough(local_platform)
