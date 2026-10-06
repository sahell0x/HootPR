from collections.abc import Callable
from decimal import Decimal

import pytest
import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.rate_limit import RateLimiter
from app.chat.router import handle_comment_event
from app.crypto import Crypto
from app.events.models import CommentCreated, EventRepo
from app.models import (
    ChatMessage,
    CreditLedgerEntry,
    Finding,
    Organization,
    PullRequest,
    Repository,
    Review,
)
from app.platforms.local import LocalPlatform
from app.worker.context import WorkerContext
from tests.factories import make_installation, make_org, make_repo
from tests.integration.test_pipeline import set_live_pr

pytestmark = pytest.mark.integration
BOT = "@hootpr-test"
REPO = EventRepo(provider="github", provider_repo_id="1001", full_name="acme/web")


def ev(
    body: str,
    *,
    cid: str = "555",
    author: str = "bob",
    thread: str | None = None,
    review_comment: bool = False,
    delivery: str = "d1",
) -> CommentCreated:
    return CommentCreated(
        provider="github",
        delivery_id=delivery,
        repo=REPO,
        pr_number=7,
        comment_id=cid,
        author_username=author,
        body=body,
        thread_ref=thread,
        installation_id=42,
        is_review_comment=review_comment,
        path="src/login.py" if review_comment else None,
        line=2 if review_comment else None,
    )


def seed(db: Session, lp: LocalPlatform, balance: str = "300") -> Organization:
    org = make_org(db, balance=balance)
    make_repo(db, org, make_installation(db, org))
    set_live_pr(lp, "2" * 40)
    return org


def chat_rows(db: Session) -> list[ChatMessage]:
    db.expire_all()
    return list(db.execute(select(ChatMessage).order_by(ChatMessage.created_at)).scalars())


def last_reply(lp: LocalPlatform) -> str:
    return lp.comments[("1001", 7)][-1].body


def chat_holds(db: Session) -> list[CreditLedgerEntry]:
    stmt = select(CreditLedgerEntry).where(CreditLedgerEntry.ref_type == "chat")
    return list(db.execute(stmt).scalars())


def test_help_is_free_reacts_and_replies_top_level(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    assert handle_comment_event(make_wctx(), ev(f"{BOT} help")) == "processed"
    [row] = chat_rows(db)
    assert (row.kind, row.command, row.status, row.credits_charged) == (
        "command",
        "help",
        "completed",
        Decimal("0.00"),
    )
    assert local_platform.reactions == [("555", "eyes")]
    body = last_reply(local_platform)
    assert body.startswith(f"<!-- hootpr:chat:{row.id} -->") and "## HootPR commands" in body
    assert row.reply_comment_id and row.finished_at is not None
    assert row.meta["provider"] == "github" and row.meta["is_review_comment"] is False


def test_bot_authored_comment_is_ignored(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:  # Review Focus #1
    seed(db, local_platform)
    ctx = make_wctx()
    assert handle_comment_event(ctx, ev(f"{BOT} review", author="hootpr-test[bot]")) == "ignored"
    assert (
        handle_comment_event(ctx, ev(f"{BOT} review", author="renovate[bot]", cid="556"))
        == "ignored"
    )
    assert chat_rows(db) == [] and local_platform.reactions == []


def test_duplicate_comment_is_handled_once(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:  # Review Focus #2
    seed(db, local_platform)
    ctx = make_wctx()
    assert handle_comment_event(ctx, ev(f"{BOT} why?", delivery="a")) == "processed"
    assert handle_comment_event(ctx, ev(f"{BOT} why?", delivery="b")) == "ignored"
    assert len(chat_rows(db)) == 1
    assert [n for n, _ in ctx.queue.calls].count("chat.run") == 1  # type: ignore[attr-defined]
    assert len(chat_holds(db)) == 1


def test_comment_without_mention_is_ignored_outside_hootpr_threads(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    assert handle_comment_event(make_wctx(), ev("looks good to me")) == "ignored"
    assert (
        handle_comment_event(make_wctx(), ev("hmm", thread="999", review_comment=True, cid="7"))
        == "ignored"
    )
    assert chat_rows(db) == []


def _seed_finding(db: Session, org: Organization, comment_id: str = "501") -> None:
    pr = db.execute(select(PullRequest)).scalar_one()
    r = Review(pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="2" * 40)
    db.add(r)
    db.flush()
    db.add(
        Finding(
            review_id=r.id,
            path="src/login.py",
            end_line=2,
            severity="minor",
            category="style",
            title="Nit",
            body="b",
            posted=True,
            provider_comment_id=comment_id,
            status="open",
            fingerprint="fp1",
        )
    )
    db.commit()


def test_reply_in_hootpr_thread_without_mention_queues_chat(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} pause"))  # creates the PR row
    _seed_finding(db, org)
    assert (
        handle_comment_event(
            ctx,
            ev("we don't care about this here", cid="9001", thread="501", review_comment=True),
        )
        == "processed"
    )
    row = chat_rows(db)[-1]
    assert (row.kind, row.command, row.status, row.thread_ref) == ("chat", None, "queued", "501")
    assert ("chat.run", (str(row.id),)) in ctx.queue.calls  # type: ignore[attr-defined]
    db.expire_all()
    # chat holds up to CHAT_HOLD_MAX (100) and settles at the metered credits later
    assert db.get(Organization, org.id).credits_balance == Decimal("200")  # type: ignore[union-attr]
    assert local_platform.reactions[-1] == ("review:9001", "eyes")


def test_auto_reply_off_needs_a_mention(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} pause"))
    _seed_finding(db, org)
    repo = db.execute(select(Repository)).scalar_one()
    repo.settings = {"chat": {"auto_reply": False}}
    db.commit()
    assert (
        handle_comment_event(ctx, ev("why?", cid="9002", thread="501", review_comment=True))
        == "ignored"
    )
    assert (
        handle_comment_event(ctx, ev(f"{BOT} why?", cid="9003", thread="501", review_comment=True))
        == "processed"
    )


def test_pause_and_resume(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} pause"))
    pr = db.execute(select(PullRequest)).scalar_one()
    assert pr.paused is True and "Reviews paused." in last_reply(local_platform)
    pr.reviewed_commits_count = 5
    db.commit()
    handle_comment_event(ctx, ev(f"{BOT} resume", cid="556"))
    db.refresh(pr)
    assert pr.paused is False and pr.reviewed_commits_count == 0
    assert "Reviews resumed." in last_reply(local_platform)


def test_review_command_is_incremental_and_bypasses_pause(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} pause"))
    pr = db.execute(select(PullRequest)).scalar_one()
    pr.last_reviewed_sha = "1" * 39 + "a"
    db.commit()
    handle_comment_event(ctx, ev(f"{BOT} review", cid="556"))
    review = db.execute(select(Review)).scalar_one()
    assert (review.trigger, review.status, review.base_sha) == (
        "command_review",
        "queued",
        "1" * 39 + "a",
    )
    assert "Review triggered." in last_reply(local_platform)
    assert "full review" in last_reply(local_platform)
    handle_comment_event(ctx, ev(f"{BOT} full review", cid="557"))
    full = db.execute(select(Review).where(Review.trigger == "command_full")).scalar_one()
    assert full.base_sha == "1" * 40
    assert "Full review triggered." in last_reply(local_platform)
    [row] = [r for r in chat_rows(db) if r.command == "review"]
    assert row.credits_charged == Decimal("0.00")  # the review holds its own credit


def test_configuration_reply_has_provenance(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = seed(db, local_platform)
    org.settings = {"reviews": {"poem": True}}
    db.commit()
    handle_comment_event(make_wctx(), ev(f"{BOT} configuration"))
    body = last_reply(local_platform)
    assert "```yaml" in body and "poem: true  # from organization settings" in body


def test_rate_limit_reply(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    handle_comment_event(make_wctx(), ev(f"{BOT} rate limit"))
    body = last_reply(local_platform)
    assert "| Reviews | 2 of 2 | now |" in body and "300 credits" in body
    assert "| Chat replies | 10 of 10 | now |" in body


def test_unsupported_and_ignore_hint_are_free(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} local commit"))
    assert "`local commit` is not available in HootPR yet." in last_reply(local_platform)
    assert chat_rows(db)[-1].command == "unsupported:local commit"
    handle_comment_event(ctx, ev(f"{BOT} ignore", cid="556"))
    assert "pull request description" in last_reply(local_platform)
    assert chat_holds(db) == []


def test_resolve_in_review_thread_gets_a_hint(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    handle_comment_event(
        make_wctx(), ev(f"{BOT} resolve", thread="501", review_comment=True, cid="9")
    )
    reply = local_platform.comments[("1001", 7)][-1]
    assert "top-level" in reply.body and reply.thread_ref == "501"
    assert local_platform.resolved == []


def test_resolve_command_resolves_open_hootpr_threads(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} pause"))
    _seed_finding(db, org)
    handle_comment_event(ctx, ev(f"{BOT} resolve", cid="556"))
    assert local_platform.resolved == ["501"]
    assert "Comments resolved." in last_reply(local_platform)
    db.expire_all()
    assert db.execute(select(Finding.status)).scalar_one() == "resolved"


def test_chat_rate_limited_and_out_of_credits(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    redis_client: redis.Redis,
) -> None:
    seed(db, local_platform, balance="4")  # below CHAT_MIN_CHARGE (5)
    handle_comment_event(make_wctx(), ev(f"{BOT} explain this"))
    row = chat_rows(db)[-1]
    assert row.status == "no_credits" and "Out of credits" in last_reply(local_platform)
    assert "hootpr:walkthrough" not in last_reply(local_platform)
    limited = make_wctx(limiter=RateLimiter(redis_client, {"review": 2, "chat": 0}))
    handle_comment_event(limited, ev(f"{BOT} explain again", cid="556"))
    assert chat_rows(db)[-1].status == "rate_limited"
    assert "Chat rate limited" in last_reply(local_platform)
    assert chat_holds(db) == []


def test_summary_and_sequence_diagram_are_chat_jobs(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} summary"))
    handle_comment_event(ctx, ev(f"{BOT} generate sequence diagram", cid="556"))
    rows = chat_rows(db)
    assert [(r.kind, r.command, r.status) for r in rows] == [
        ("command", "summary", "queued"),
        ("command", "sequence_diagram", "queued"),
    ]
    assert [n for n, _ in ctx.queue.calls].count("chat.run") == 2  # type: ignore[attr-defined]
    assert len(chat_holds(db)) == 2


def test_enqueue_failure_refunds(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    org = seed(db, local_platform)

    class Broken:
        def enqueue(self, name: str, *args: object) -> None:
            raise RuntimeError("broker down")

    handle_comment_event(make_wctx(queue=Broken()), ev(f"{BOT} why?"))
    row = chat_rows(db)[-1]
    assert row.status == "failed" and "no credit was charged" in last_reply(local_platform)
    db.expire_all()
    assert db.get(Organization, org.id).credits_balance == Decimal("300")  # type: ignore[union-attr]


def test_unknown_repo_is_ignored(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    assert handle_comment_event(make_wctx(), ev(f"{BOT} help")) == "ignored"


def test_gitlab_fixture_notes(
    db: Session, make_wctx: Callable[..., WorkerContext], crypto: Crypto
) -> None:
    from app.platforms.base import InlineComment, RepoRef
    from app.platforms.base import PullRequest as PlatformPR
    from app.platforms.gitlab.webhooks import parse_event
    from tests.fixtures import load_fixture

    gl = LocalPlatform("gitlab")
    ref = RepoRef("gitlab", "2002", "acme-group/api")
    org = make_org(db, provider="gitlab", provider_org_id="77", slug="acme-group", balance="300")
    inst = make_installation(db, org, gitlab_token="glpat-x", crypto=crypto)
    make_repo(db, org, inst, provider="gitlab", provider_repo_id="2002", full_name="acme-group/api")
    gl.add_pull_request(
        ref,
        PlatformPR(3, "Fix", "", "carol", "open", False, "main", "f", "1" * 40, "2" * 40, (), "u"),
        [],
    )  # fmt: skip
    ctx = make_wctx(platforms=lambda s, repo: gl)

    top = load_fixture("gitlab", "note.merge_request")
    top["object_attributes"]["note"] = "@hootpr-bot help"
    event = parse_event("Note Hook", top, "g1")
    assert isinstance(event, CommentCreated)
    assert handle_comment_event(ctx, event) == "processed"
    reply = gl.comments[("2002", 3)][-1]
    assert reply.thread_ref == "abc123" and "## HootPR commands" in reply.body
    assert "`@hootpr-bot review`" in reply.body
    assert gl.reactions == [("3:8001", "eyes")]

    # A reply without a mention inside a HootPR discussion is a chat message.
    [disc] = gl.post_review(ref, 3, "2" * 40, None, [InlineComment("src/login.py", 2, "x")])
    pr = db.execute(select(PullRequest)).scalar_one()
    r = Review(pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha="2" * 40)
    db.add(r)
    db.flush()
    db.add(Finding(review_id=r.id, path="src/login.py", end_line=2, severity="minor",
                   category="style", title="Nit", body="b", posted=True,
                   provider_comment_id=disc, status="open", fingerprint="fp"))  # fmt: skip
    db.commit()
    diff_note = load_fixture("gitlab", "note.merge_request.diff_note")
    diff_note["object_attributes"]["discussion_id"] = disc
    event = parse_event("Note Hook", diff_note, "g2")
    assert isinstance(event, CommentCreated)
    assert handle_comment_event(ctx, event) == "processed"
    row = chat_rows(db)[-1]
    assert (row.kind, row.status, row.thread_ref) == ("chat", "queued", disc)
    assert row.meta["provider"] == "gitlab" and row.meta["path"] == "src/login.py"
    # The bot's own note is never answered.
    own = load_fixture("gitlab", "note.merge_request")
    own["user"]["username"] = "hootpr-bot"
    own["object_attributes"]["id"] = 8002
    event = parse_event("Note Hook", own, "g3")
    assert isinstance(event, CommentCreated)
    assert handle_comment_event(ctx, event) == "ignored"


def test_github_review_comment_fixture_replies_in_thread(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    from app.platforms.github.webhooks import parse_event
    from tests.fixtures import load_fixture

    seed(db, local_platform)
    payload = load_fixture("github", "pull_request_review_comment.created")
    payload["comment"]["body"] = f"{BOT} configuration"
    event = parse_event("pull_request_review_comment", payload, "d9")
    assert isinstance(event, CommentCreated)
    assert handle_comment_event(make_wctx(), event) == "processed"
    reply = local_platform.comments[("1001", 7)][-1]
    assert reply.thread_ref == "501" and "```yaml" in reply.body
    assert local_platform.reactions == [("review:9001", "eyes")]


@pytest.mark.parametrize(
    "phrase", ["approve", "resolve", "pause", "resume", "review", "full review", "summary",
               "rate limit"]
)  # fmt: skip
def test_commenter_without_write_access_cannot_run_privileged_commands(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    phrase: str,
) -> None:
    org = seed(db, local_platform)
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} help", cid="1"))  # creates the PR row
    _seed_finding(db, org)
    local_platform.readers.add("mallory")
    assert handle_comment_event(ctx, ev(f"{BOT} {phrase}", author="mallory")) == "processed"
    row = chat_rows(db)[-1]
    assert row.status == "completed" and row.meta["can_write"] is False
    assert "write access" in last_reply(local_platform)
    assert local_platform.resolved == [] and local_platform.reviews == []
    assert ctx.queue.calls == []  # type: ignore[attr-defined]
    assert chat_holds(db) == []
    db.expire_all()
    assert db.execute(select(PullRequest.paused)).scalar_one() is False
    assert db.execute(select(Finding.status)).scalar_one() == "open"


def test_commenter_without_write_access_can_read_and_ask(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    local_platform.readers.add("mallory")
    ctx = make_wctx()
    handle_comment_event(ctx, ev(f"{BOT} help", author="mallory"))
    assert "## HootPR commands" in last_reply(local_platform)
    handle_comment_event(ctx, ev(f"{BOT} configuration", author="mallory", cid="556"))
    assert "```yaml" in last_reply(local_platform)
    handle_comment_event(ctx, ev(f"{BOT} why is this slow?", author="mallory", cid="557"))
    row = chat_rows(db)[-1]
    assert (row.kind, row.status, row.meta["can_write"]) == ("chat", "queued", False)


def test_github_association_skips_the_permission_lookup(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    local_platform.permission_error = RuntimeError("no API call expected")
    event = ev(f"{BOT} pause")
    event.author_association = "COLLABORATOR"
    handle_comment_event(make_wctx(), event)
    assert "Reviews paused." in last_reply(local_platform)
    assert chat_rows(db)[-1].meta["can_write"] is True


def test_permission_lookup_failure_fails_closed(
    db: Session, local_platform: LocalPlatform, make_wctx: Callable[..., WorkerContext]
) -> None:
    seed(db, local_platform)
    local_platform.permission_error = RuntimeError("API down")
    event = ev(f"{BOT} pause")
    event.author_association = "CONTRIBUTOR"
    handle_comment_event(make_wctx(), event)
    assert "write access" in last_reply(local_platform)
    db.expire_all()
    assert db.execute(select(PullRequest.paused)).scalar_one() is False


def test_gitlab_reporter_cannot_approve(
    db: Session, make_wctx: Callable[..., WorkerContext], crypto: Crypto
) -> None:
    from app.platforms.base import PullRequest as PlatformPR
    from app.platforms.base import RepoRef
    from app.platforms.gitlab.webhooks import parse_event
    from tests.fixtures import load_fixture

    gl = LocalPlatform("gitlab")
    ref = RepoRef("gitlab", "2002", "acme-group/api")
    org = make_org(db, provider="gitlab", provider_org_id="77", slug="acme-group", balance="300")
    inst = make_installation(db, org, gitlab_token="glpat-x", crypto=crypto)
    make_repo(db, org, inst, provider="gitlab", provider_repo_id="2002", full_name="acme-group/api")
    gl.add_pull_request(
        ref,
        PlatformPR(3, "Fix", "", "carol", "open", False, "main", "f", "1" * 40, "2" * 40, (), "u"),
        [],
    )  # fmt: skip
    top = load_fixture("gitlab", "note.merge_request")
    top["object_attributes"]["note"] = "@hootpr-bot approve"
    gl.readers.add(str(top["user"]["username"]))
    event = parse_event("Note Hook", top, "g1")
    assert isinstance(event, CommentCreated)
    assert handle_comment_event(make_wctx(platforms=lambda s, repo: gl), event) == "processed"
    assert "write access" in gl.comments[("2002", 3)][-1].body
    assert gl.approvals == [] and gl.resolved == []
