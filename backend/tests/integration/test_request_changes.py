from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.router import handle_comment_event
from app.events.models import EventRepo, ThreadStatusChanged
from app.events.processing import _dispatch
from app.models import Finding, PullRequest, Review
from app.platforms.base import InlineComment
from app.platforms.local import LocalPlatform
from app.review.blocking import refresh_blocking
from app.worker.context import WorkerContext
from tests.factories import make_installation, make_org, make_pr, make_repo
from tests.fixtures import load_fixture
from tests.integration.test_chat_router import BOT, ev
from tests.integration.test_pipeline import REF, set_live_pr

pytestmark = pytest.mark.integration


def seed(
    db: Session, lp: LocalPlatform, *, workflow: bool = True, state: str = "changes_requested"
) -> PullRequest:
    org = make_org(db, balance="3")
    repo = make_repo(db, org, make_installation(db, org))
    repo.settings = {"reviews": {"request_changes_workflow": workflow}}
    set_live_pr(lp, "2" * 40)
    pr = make_pr(db, repo)
    pr.blocking_state = state
    [cid] = lp.post_review(
        REF, 7, "2" * 40, None, [InlineComment("src/login.py", 2, "**SQL injection**")]
    )
    r = Review(pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="2" * 40)
    db.add(r)
    db.flush()
    db.add(
        Finding(
            review_id=r.id,
            path="src/login.py",
            end_line=2,
            severity="critical",
            category="security",
            title="SQL injection",
            body="b",
            posted=True,
            provider_comment_id=cid,
            status="open",
            fingerprint="fp",
        )
    )
    db.commit()
    return pr


def finding_status(db: Session) -> str:
    db.expire_all()
    return db.execute(select(Finding.status)).scalar_one()


def test_resolving_last_blocking_thread_flips_status_and_approves(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    pr = seed(db, local_platform)
    ctx = make_wctx()
    assert refresh_blocking(ctx, pr.id) == "changes_requested"
    assert local_platform.statuses[-1].state == "failure"
    assert local_platform.statuses[-1].title == "Changes requested"
    local_platform.resolve_thread(REF, 7, "1")
    assert refresh_blocking(ctx, pr.id) == "approved"
    assert local_platform.statuses[-1].state == "success"
    assert local_platform.approvals == [("1001", 7)]
    assert finding_status(db) == "resolved"
    assert refresh_blocking(ctx, pr.id) == "approved"
    assert local_platform.approvals == [("1001", 7)]  # approve once per transition


def test_reopening_a_thread_requests_changes_again(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    pr = seed(db, local_platform)
    ctx = make_wctx()
    local_platform.resolve_thread(REF, 7, "1")
    refresh_blocking(ctx, pr.id)
    local_platform.resolved.remove("1")
    assert refresh_blocking(ctx, pr.id) == "changes_requested"
    assert finding_status(db) == "open"


def test_no_blocking_findings_from_none_does_not_approve(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    pr = seed(db, local_platform, state="none")
    local_platform.resolve_thread(REF, 7, "1")
    assert refresh_blocking(make_wctx(), pr.id) == "none"
    assert local_platform.approvals == [] and local_platform.statuses[-1].state == "success"


def test_workflow_off_is_a_no_op(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    pr = seed(db, local_platform, workflow=False, state="none")
    assert refresh_blocking(make_wctx(), pr.id) is None and local_platform.statuses == []


def test_thread_event_dispatch_refreshes(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    local_platform.resolve_thread(REF, 7, "1")
    event = ThreadStatusChanged(
        provider="github",
        delivery_id="t1",
        repo=EventRepo(provider="github", provider_repo_id="1001", full_name="acme/web"),
        pr_number=7,
        thread_ref="1",
        resolved=True,
        installation_id=42,
    )
    assert _dispatch(make_wctx(), event.model_dump()) == "processed"
    db.expire_all()
    assert db.execute(select(PullRequest.blocking_state)).scalar_one() == "approved"
    unknown = event.model_copy(update={"pr_number": 99})
    assert _dispatch(make_wctx(), unknown.model_dump()) == "ignored"


def test_gitlab_mr_update_refreshes(db: Session, make_wctx: Callable[..., WorkerContext]) -> None:
    from app.platforms.base import PullRequest as PlatformPR
    from app.platforms.base import RepoRef
    from app.platforms.gitlab.webhooks import parse_event

    gl = LocalPlatform("gitlab")
    ref = RepoRef("gitlab", "2002", "acme-group/api")
    org = make_org(db, provider="gitlab", provider_org_id="77", slug="acme-group", balance="3")
    repo = make_repo(
        db,
        org,
        make_installation(db, org),
        provider="gitlab",
        provider_repo_id="2002",
        full_name="acme-group/api",
    )
    repo.settings = {"reviews": {"request_changes_workflow": True}}
    pr = make_pr(db, repo, number=3)
    pr.blocking_state = "changes_requested"
    gl.add_pull_request(
        ref,
        PlatformPR(
            3,
            "Fix pagination",
            "",
            "carol",
            "open",
            False,
            "main",
            "fix",
            "1" * 40,
            "2" * 40,
            (),
            "u",
        ),
        [],
    )
    [cid] = gl.post_review(ref, 3, "2" * 40, None, [InlineComment("a.py", 1, "x")])
    r = Review(pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="2" * 40)
    db.add(r)
    db.flush()
    db.add(
        Finding(
            review_id=r.id,
            path="a.py",
            end_line=1,
            severity="major",
            category="bug",
            title="t",
            body="b",
            posted=True,
            provider_comment_id=cid,
            status="open",
            fingerprint="fp",
        )
    )
    db.commit()
    gl.resolve_thread(ref, 3, cid)
    event = parse_event(
        "Merge Request Hook", load_fixture("gitlab", "merge_request.update_title"), "g"
    )
    assert event is not None
    ctx = make_wctx(platforms=lambda s, repo: gl)
    assert _dispatch(ctx, event.model_dump()) == "processed"
    db.expire_all()
    assert db.execute(select(PullRequest.blocking_state)).scalar_one() == "approved"
    assert gl.approvals == [("2002", 3)] and gl.reviews[-1].event == "APPROVE"


def test_resolve_and_approve_commands(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} approve", cid="800"))
    assert local_platform.resolved == ["1"]
    assert local_platform.approvals == [("1001", 7)]
    assert (
        "Comments resolved and changes approved." in local_platform.comments[("1001", 7)][-1].body
    )


def test_approve_from_none_approves_once(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform, state="none")
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} approve", cid="800"))
    handle_comment_event(ctx, ev(f"{BOT} approve", cid="801"))
    assert local_platform.approvals == [("1001", 7)]


def test_resolve_command_with_workflow_flips_status(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    handle_comment_event(make_wctx(), ev(f"{BOT} resolve", cid="802"))
    assert local_platform.statuses[-1].state == "success"
    db.expire_all()
    assert db.execute(select(PullRequest.blocking_state)).scalar_one() == "approved"
    assert "Comments resolved." in local_platform.comments[("1001", 7)][-1].body


def test_approve_without_workflow_explains(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform, workflow=False, state="none")
    handle_comment_event(make_wctx(), ev(f"{BOT} approve", cid="801"))
    body = local_platform.comments[("1001", 7)][-1].body
    assert "request_changes_workflow" in body and local_platform.approvals == []


NEW_HEAD = "3" * 40


@pytest.mark.parametrize("path", ["no_credits", "skipped", "no_reviewable_files"])
def test_open_blocking_findings_keep_the_new_head_failing(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    path: str,
) -> None:
    from app.models import Organization
    from app.platforms.diff import build_file_diff
    from app.review.pipeline import start_review
    from tests.integration.test_pipeline import run_queued

    pr = seed(db, local_platform)
    set_live_pr(local_platform, NEW_HEAD)  # the author pushes again
    if path == "no_credits":
        db.execute(select(Organization)).scalar_one().credits_balance = 0  # type: ignore[assignment]
    elif path == "skipped":
        pr.paused = True
    else:
        local_platform.diffs[("1001", 7)] = [
            build_file_diff("pnpm-lock.yaml", "@@ -1 +1 @@\n-a\n+b\n", "modified")
        ]
    db.commit()
    ctx = make_wctx()
    start_review(ctx, pr.id, "incremental")
    run_queued(ctx)
    last = [st for st in local_platform.statuses if st.sha == NEW_HEAD][-1]
    assert (last.state, last.title) == ("failure", "Changes requested")
    assert local_platform.approvals == []


def test_skip_without_blocking_findings_stays_neutral(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    from app.review.pipeline import start_review

    pr = seed(db, local_platform)
    local_platform.resolve_thread(REF, 7, "1")
    refresh_blocking(make_wctx(), pr.id)
    set_live_pr(local_platform, NEW_HEAD)
    db.expire_all()
    pr = db.get(PullRequest, pr.id)  # type: ignore[assignment]
    pr.paused = True
    db.commit()
    start_review(make_wctx(), pr.id, "incremental")
    last = [st for st in local_platform.statuses if st.sha == NEW_HEAD][-1]
    assert last.state == "neutral"
