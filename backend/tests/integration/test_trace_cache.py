from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import AgentStep, Repository, Review, ReviewCacheEntry, ReviewTask, ToolRun
from app.review.cache import SqlReviewCache, cache_key, purge_review_cache
from app.review.schemas import PlanTask
from app.review.tool_results import ToolRunRecord
from app.review.trace import SqlTraceSink, StageRecord
from tests.factories import make_installation, make_org, make_pr, make_repo

pytestmark = pytest.mark.integration


def seed(db: Session) -> tuple[Repository, Review]:
    org = make_org(db)
    repo = make_repo(db, org, make_installation(db, org))
    pr = make_pr(db, repo)
    review = Review(
        pr_id=pr.id, org_id=org.id, trigger="auto", head_sha=pr.head_sha, status="running"
    )
    db.add(review)
    db.commit()
    return repo, review


def test_sql_trace_sink_appends_live(db: Session, session_factory: sessionmaker[Session]) -> None:
    _, review = seed(db)
    sink = SqlTraceSink(session_factory, review.id)
    now = datetime.now(UTC)
    sink.stage(StageRecord("diff", "ok", now, 5, "2 files"))
    sink.stage(StageRecord("sandbox", "failed", now, 9, "CloneError: x"))
    tid = sink.task_created(
        0,
        PlanTask(
            title="Auth", files=["a.py"], focus=["security"], rationale="r", related_symbols=["f"]
        ),
    )
    sink.agent_step(tid, "tool_call", "shell", {"cmd": "rg x"}, None, None)
    sink.agent_step(tid, "tool_result", "shell", {}, "out", 12)
    sink.task_status(tid, "done", "summary")
    sink.tool_runs([ToolRunRecord("ruff", "ok", 10, 1, "")])
    db.expire_all()
    stages = db.get(Review, review.id).stages  # type: ignore[union-attr]
    assert [s["name"] for s in stages] == ["diff", "sandbox"]
    assert stages[1]["detail"] == "CloneError: x"
    task = db.get(ReviewTask, tid)
    assert task is not None and task.status == "done" and task.focus == ["security"]
    assert task.summary == "summary" and task.related_symbols == ["f"]
    assert [a.step_no for a in db.query(AgentStep).order_by(AgentStep.step_no)] == [1, 2]
    assert db.query(ToolRun).one().tool == "ruff"


def test_review_cache_roundtrip_and_purge(
    db: Session, session_factory: sessionmaker[Session]
) -> None:
    repo, _ = seed(db)
    cache = SqlReviewCache(session_factory, repo.id)
    key = cache_key("graph", "a.py")
    assert cache.get("s" * 40, "graph", key) is None
    cache.put("s" * 40, "graph", key, {"version": 1, "symbols": []})
    cache.put("s" * 40, "graph", key, {"version": 1, "symbols": [1]})  # upsert
    assert cache.get("s" * 40, "graph", key) == {"version": 1, "symbols": [1]}
    tiny = SqlReviewCache(session_factory, repo.id, max_bytes=10)
    tiny.put("t" * 40, "graph", key, {"big": "x" * 1000})
    assert tiny.get("t" * 40, "graph", key) is None  # oversize payloads are not cached
    assert purge_review_cache(db, ttl_days=7, now=datetime.now(UTC)) == 0
    n = purge_review_cache(db, ttl_days=7, now=datetime.now(UTC) + timedelta(days=8))
    db.commit()
    assert n == 1 and db.query(ReviewCacheEntry).count() == 0
