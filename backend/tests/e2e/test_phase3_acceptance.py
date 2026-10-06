"""Phase 3 'Done when' (spec §16 row 3): every @hootpr command on GitHub and GitLab, driven by the
recorded comment webhooks through /api/webhooks/* → events.process → chat.run, against respx-mocked
provider APIs. Asserts the exact provider calls and reply bodies."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.pricing import estimate_review_hold
from app.chat.run import run_chat
from app.crypto import Crypto
from app.events.processing import process_delivery
from app.models import ChatMessage, Finding, Learning, Organization, Review
from app.platforms.base import FileDiff
from app.platforms.base import PullRequest as PlatformPR
from app.platforms.diff import build_file_diff
from app.platforms.factory import make_platform_factory
from app.platforms.local import LocalPlatform
from app.review.pipeline import handle_pr_event, run_review
from app.sandbox.local import LocalSandboxManager
from app.settings import Settings
from app.worker.context import WorkerContext
from tests.factories import make_installation, make_org, make_pr, make_repo
from tests.fakes.engine_llm import EngineFakeLLM, make_test_gateway, tool_call
from tests.fakes.kv import DictKV
from tests.fakes.sandbox import FakeSandboxManager
from tests.fixtures import fixture_bytes, sign_github
from tests.helpers_git import make_git_repo, write_stub_tools
from tests.integration.test_pipeline import REF, pr_event, run_queued

pytestmark = pytest.mark.integration
GH = "https://api.github.com/repos/acme/web"
GL = "https://gitlab.com/api/v4/projects/2002"
HEAD, BASE = "2" * 40, "1" * 40


@dataclass
class Env:
    provider: str
    mention: str
    ctx: WorkerContext
    fake: EngineFakeLLM
    head: str = HEAD
    base: str = BASE
    files: list[FileDiff] = field(default_factory=lambda: list(DEFAULT_FILES))
    replies: list[str] = field(default_factory=list)
    calls: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _record(env: Env, name: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        env.calls.setdefault(name, []).append(body)
        if name in ("reply", "comment", "note_reply"):
            env.replies.append(body.get("body", ""))
        return httpx.Response(201, json={"id": 1000 + len(env.replies), "notes": [{"id": 1}]})

    return handler


DEFAULT_FILES = [build_file_diff("src/login.py", "@@ -1 +1,2 @@\n a\n+b\n", "modified")]


def github_routes(mock: respx.MockRouter, env: Env) -> None:
    pr = {
        "number": 7,
        "title": "Login",
        "body": "",
        "state": "open",
        "draft": False,
        "html_url": "https://github.com/acme/web/pull/7",
        "user": {"login": "alice"},
        "labels": [],
        "base": {"ref": "main", "sha": env.base},
        "head": {"ref": "f", "sha": env.head},
    }
    files = [
        {
            "filename": f.path,
            "status": f.status,
            "additions": f.additions,
            "deletions": f.deletions,
            "patch": f.patch,
        }
        for f in env.files
    ]
    mock.get(f"{GH}/pulls/7").mock(return_value=httpx.Response(200, json=pr))
    mock.patch(f"{GH}/pulls/7").mock(side_effect=_record(env, "pr_patch"))
    mock.get(f"{GH}/contents/.hootpr.yaml").mock(return_value=httpx.Response(404))
    mock.get(f"{GH}/pulls/7/files").mock(return_value=httpx.Response(200, json=files))
    mock.get(url__regex=rf"{GH}/compare/.*").mock(
        return_value=httpx.Response(200, json={"files": files})
    )
    mock.get(url__regex=rf"{GH}/pulls/7/reviews/\d+/comments").mock(
        return_value=httpx.Response(200, json=[{"id": 601}])
    )
    mock.get(f"{GH}/issues/7/comments").mock(return_value=httpx.Response(200, json=[]))
    mock.get(f"{GH}/pulls/7/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 501,
                    "user": {"login": "hootpr-test[bot]"},
                    "body": "**Nit**",
                    "path": "src/login.py",
                    "line": 2,
                }
            ],
        )
    )
    mock.post(f"{GH}/issues/7/comments").mock(side_effect=_record(env, "comment"))
    mock.post(url__regex=rf"{GH}/pulls/7/comments/\d+/replies").mock(
        side_effect=_record(env, "reply")
    )
    mock.post(url__regex=rf"{GH}/(issues|pulls)/comments/\d+/reactions").mock(
        side_effect=_record(env, "reaction")
    )
    mock.post(f"{GH}/check-runs").mock(side_effect=_record(env, "check"))
    mock.patch(url__regex=rf"{GH}/issues/comments/\d+").mock(side_effect=_record(env, "comment"))
    mock.post(f"{GH}/pulls/7/reviews").mock(side_effect=_record(env, "review"))
    mock.post("https://api.github.com/graphql").mock(side_effect=_graphql(env))
    mock.get(url__regex=rf"{GH}/collaborators/[^/]+/permission").mock(side_effect=_gh_permission)


def _graphql(env: Env) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        env.calls.setdefault("graphql", []).append(body)
        if "resolveReviewThread" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "resolveReviewThread": {"thread": {"id": "PRRT_1", "isResolved": True}}
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "PRRT_1",
                                        "isResolved": False,
                                        "comments": {"nodes": [{"databaseId": 501}]},
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        )

    return handler


def gitlab_routes(mock: respx.MockRouter, env: Env) -> None:
    mr = {
        "iid": 3,
        "title": "Login",
        "description": "",
        "state": "opened",
        "draft": False,
        "source_branch": "f",
        "target_branch": "main",
        "sha": env.head,
        "web_url": "https://gitlab.com/acme-group/api/-/merge_requests/3",
        "author": {"username": "carol"},
        "labels": [],
        "diff_refs": {"base_sha": env.base, "head_sha": env.head, "start_sha": env.base},
    }
    diffs = [
        {
            "new_path": f.path,
            "old_path": f.path,
            "diff": f.patch,
            "new_file": f.status == "added",
            "renamed_file": False,
            "deleted_file": False,
        }
        for f in env.files
    ]
    mock.get(f"{GL}/merge_requests/3").mock(return_value=httpx.Response(200, json=mr))
    mock.put(f"{GL}/merge_requests/3").mock(side_effect=_record(env, "mr_put"))
    mock.get(f"{GL}/repository/files/.hootpr.yaml/raw").mock(return_value=httpx.Response(404))
    mock.get(f"{GL}/merge_requests/3/diffs").mock(return_value=httpx.Response(200, json=diffs))
    mock.get(url__regex=rf"{GL}/repository/compare.*").mock(
        return_value=httpx.Response(200, json={"diffs": diffs})
    )
    mock.post(f"{GL}/merge_requests/3/discussions").mock(side_effect=_record(env, "discussion"))
    mock.get(f"{GL}/merge_requests/3/discussions").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "disc-501",
                    "notes": [
                        {
                            "id": 1,
                            "author": {"username": "hootpr-bot"},
                            "body": "**Nit**",
                            "resolvable": True,
                            "resolved": False,
                            "position": {"new_path": "src/login.py", "new_line": 2},
                        }
                    ],
                }
            ],
        )
    )
    mock.post(url__regex=rf"{GL}/merge_requests/3/discussions/[^/]+/notes").mock(
        side_effect=_record(env, "note_reply")
    )
    mock.put(url__regex=rf"{GL}/merge_requests/3/discussions/[^/]+").mock(
        side_effect=_record(env, "resolve")
    )
    mock.post(url__regex=rf"{GL}/merge_requests/3/notes/\d+/award_emoji").mock(
        side_effect=_record(env, "reaction")
    )
    mock.get(f"{GL}/merge_requests/3/notes").mock(return_value=httpx.Response(200, json=[]))
    mock.post(f"{GL}/merge_requests/3/notes").mock(side_effect=_record(env, "comment"))
    mock.post(f"{GL}/statuses/{env.head}").mock(side_effect=_record(env, "check"))
    mock.put(url__regex=rf"{GL}/merge_requests/3/notes/\d+").mock(
        side_effect=_record(env, "comment")
    )
    mock.post(f"{GL}/merge_requests/3/approve").mock(side_effect=_record(env, "approve"))
    mock.get("https://gitlab.com/api/v4/user").mock(
        return_value=httpx.Response(200, json={"id": 5})
    )
    mock.get(f"{GL}/members/all").mock(side_effect=_gl_members)


READERS = {"mallory"}  # commenters without write access in these fixtures


def _gh_permission(request: httpx.Request) -> httpx.Response:
    user = request.url.path.split("/")[-2]
    perm = "read" if user in READERS else "write"
    return httpx.Response(200, json={"permission": perm, "role_name": perm})


def _gl_members(request: httpx.Request) -> httpx.Response:
    user = request.url.params["query"]
    level = 20 if user in READERS else 30
    return httpx.Response(200, json=[{"username": user, "access_level": level}])


def setup(
    db: Session,
    provider: str,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
    *,
    workflow: bool = False,
    head: str = HEAD,
    base: str = BASE,
    files: list[FileDiff] | None = None,
) -> Env:
    fake = EngineFakeLLM()
    if provider == "github":
        org = make_org(db, balance="300")
        repo = make_repo(db, org, make_installation(db, org))
        kv, mention, number, thread = (
            DictKV({"gh:insttoken:42": "ghs_e2e"}),
            "@hootpr-test",
            7,
            "501",
        )
    else:
        org = make_org(
            db, provider="gitlab", provider_org_id="10", slug="gl", kind="group", balance="300"
        )
        inst = make_installation(
            db, org, github_installation_id=None, gitlab_token="glpat-bot", crypto=crypto
        )
        repo = make_repo(
            db,
            org,
            inst,
            provider="gitlab",
            provider_repo_id="2002",
            full_name="acme-group/api",
            webhook_secret="hooksecret",
            crypto=crypto,
        )
        kv, mention, number, thread = DictKV(), "@hootpr-bot", 3, "disc-501"
    repo.settings = {"reviews": {"request_changes_workflow": workflow}}
    pr = make_pr(db, repo, number=number, head_sha=head, base_sha=base)
    pr.last_reviewed_sha = "3" * 40
    r = Review(pr_id=pr.id, org_id=org.id, trigger="auto", status="completed", head_sha=head)
    db.add(r)
    db.flush()
    db.add(
        Finding(
            review_id=r.id,
            path="src/login.py",
            end_line=2,
            severity="major",
            category="bug",
            title="Nit",
            body="b",
            posted=True,
            provider_comment_id=thread,
            status="open",
            fingerprint="fp",
        )
    )
    pr.blocking_state = "changes_requested" if workflow else "none"
    db.commit()
    ctx = make_wctx(
        platforms=make_platform_factory(int_settings, kv, crypto),
        sandboxes=FakeSandboxManager(),
        llm=lambda: make_test_gateway(fake)[0],
    )
    return Env(provider, mention, ctx, fake, head, base, list(files or DEFAULT_FILES))


async def send(
    client: httpx.AsyncClient,
    env: Env,
    body: str,
    *,
    delivery: str,
    author: str = "bob",
    in_thread: bool = False,
) -> None:
    if env.provider == "github":
        name = "pull_request_review_comment.created" if in_thread else "issue_comment.created"
        payload = json.loads(fixture_bytes("github", name))
        payload["comment"]["body"], payload["comment"]["user"]["login"] = body, author
        if author in READERS:
            payload["comment"]["author_association"] = "NONE"
        raw = json.dumps(payload).encode()
        event = "pull_request_review_comment" if in_thread else "issue_comment"
        headers = {
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": sign_github("gh-webhook-secret", raw),
        }
        resp = await client.post("/api/webhooks/github", content=raw, headers=headers)
    else:
        name = "note.merge_request.diff_note" if in_thread else "note.merge_request"
        payload = json.loads(fixture_bytes("gitlab", name))
        payload["object_attributes"]["note"], payload["user"]["username"] = body, author
        if in_thread:
            payload["object_attributes"]["discussion_id"] = "disc-501"
        raw = json.dumps(payload).encode()
        resp = await client.post(
            "/api/webhooks/gitlab",
            content=raw,
            headers={
                "X-Gitlab-Event": "Note Hook",
                "X-Gitlab-Token": "hooksecret",
                "X-Gitlab-Event-UUID": delivery,
            },
        )
    assert resp.status_code == 202


def drain(
    app: FastAPI, env: Env, *, run_reviews: bool = False
) -> list[tuple[str, tuple[Any, ...]]]:
    """Process webhook deliveries, then queued chat jobs (and review jobs when asked).
    Returns every worker task that was queued."""
    for _name, args in app.state.queue.calls:
        process_delivery(env.ctx, str(args[0]), args[1])
    app.state.queue.calls.clear()
    queued = list(env.ctx.queue.calls)  # type: ignore[attr-defined]
    env.ctx.queue.calls.clear()  # type: ignore[attr-defined]
    for name, args in queued:
        if name == "chat.run":
            run_chat(env.ctx, UUID(str(args[0])))
        elif name == "review.run" and run_reviews:
            run_review(env.ctx, UUID(str(args[0])))
    return queued


def routes(mock: respx.MockRouter, env: Env) -> None:
    (github_routes if env.provider == "github" else gitlab_routes)(mock, env)


PROVIDERS = ["github", "gitlab"]
FREE_CASES = [
    ("help", "## HootPR commands"),
    ("configuration", "```yaml"),
    ("rate limit", "| Reviews | 2 of 2 | now |"),
    ("pause", "Reviews paused."),
    ("resume", "Reviews resumed."),
    ("local commit", "`local commit` is not available in HootPR yet."),
    ("ignore", "pull request description"),
]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("phrase,expected", FREE_CASES)
async def test_free_commands(
    provider: str,
    phrase: str,
    expected: str,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    env = setup(db, provider, int_settings, crypto, make_wctx)
    await send(client, env, f"{env.mention} {phrase}", delivery=f"{provider}-{phrase}")
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env)
    assert env.calls.get("reaction"), "👀 reaction missing"
    assert any(expected in r for r in env.replies), env.replies
    assert all(r.startswith(("@bob", "<!-- hootpr:chat:")) for r in env.replies)
    db.expire_all()
    assert db.execute(select(Organization.credits_balance)).scalar_one() == Decimal("300")


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "phrase,trigger,base",
    [("review", "command_review", None), ("full review", "command_full", BASE)],
)
async def test_review_commands(
    provider: str,
    phrase: str,
    trigger: str,
    base: str | None,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    env = setup(db, provider, int_settings, crypto, make_wctx)
    await send(client, env, f"{env.mention} {phrase}", delivery=f"{provider}-{phrase}")
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        queued = drain(app, env)
    new = db.execute(select(Review).where(Review.trigger == trigger)).scalar_one()
    assert new.status == "queued" and new.base_sha == (base or "3" * 40)
    assert ("review.run", (str(new.id),)) in queued
    assert any("Review triggered." in r or "Full review triggered." in r for r in env.replies)
    assert env.calls.get("check"), "in-progress status missing"
    # The queued review holds min(estimate, balance) until it settles; the mocked PR carries no
    # size, so the estimate is review_hold_max (capped at the balance).
    db.expire_all()
    hold = min(estimate_review_hold(None, None, int_settings), Decimal("300"))
    assert db.execute(select(Organization.credits_balance)).scalar_one() == Decimal("300") - hold


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_resolve_command(
    provider: str,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    env = setup(db, provider, int_settings, crypto, make_wctx)
    await send(client, env, f"{env.mention} resolve", delivery=f"{provider}-resolve")
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env)
    if provider == "github":
        assert any("resolveReviewThread" in c["query"] for c in env.calls["graphql"])
    else:
        assert env.calls["resolve"]
    assert not env.calls.get("review") and not env.calls.get("approve")
    assert any("Comments resolved." in r for r in env.replies)
    db.expire_all()
    assert db.execute(select(Finding.status)).scalar_one() == "resolved"
    assert db.execute(select(Organization.credits_balance)).scalar_one() == Decimal("300")


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_resolve_and_approve(
    provider: str,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    env = setup(db, provider, int_settings, crypto, make_wctx, workflow=True)
    await send(client, env, f"{env.mention} approve", delivery=f"{provider}-approve")
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env)
    if provider == "github":
        assert any("resolveReviewThread" in c["query"] for c in env.calls["graphql"])
        assert [c["event"] for c in env.calls["review"]] == ["APPROVE"]
    else:
        assert env.calls["resolve"] and env.calls["approve"]
    assert any("Comments resolved and changes approved." in r for r in env.replies)
    db.expire_all()
    assert db.execute(select(Finding.status)).scalar_one() == "resolved"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_commenter_without_write_access_cannot_approve(
    provider: str,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    env = setup(db, provider, int_settings, crypto, make_wctx, workflow=True)
    await send(client, env, f"{env.mention} approve", delivery=f"{provider}-ro", author="mallory")
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env)
    assert any("needs write access" in r for r in env.replies)
    assert "approve" not in env.calls and "review" not in env.calls and "resolve" not in env.calls
    assert not any("resolveReviewThread" in c["query"] for c in env.calls.get("graphql", []))
    db.expire_all()
    assert db.execute(select(Finding.status)).scalar_one() == "open"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "body,in_thread",
    [
        ("{m} why is this a problem?", False),
        ("we do this on purpose", True),
        ("{m} summary", False),
        ("{m} generate sequence diagram", False),
    ],
)
async def test_llm_replies_are_charged_metered_credits(
    provider: str,
    body: str,
    in_thread: bool,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    env = setup(db, provider, int_settings, crypto, make_wctx)
    await send(
        client,
        env,
        body.format(m=env.mention),
        delivery=f"{provider}-{body[:12]}",
        in_thread=in_thread,
    )
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env)
    row = db.execute(select(ChatMessage)).scalar_one()
    assert row.status == "completed", row.error
    db.expire_all()  # chat hold settled at the fake LLM's usage, i.e. the minimum charge
    assert row.credits_charged == int_settings.chat_min_charge
    balance = db.execute(select(Organization.credits_balance)).scalar_one()
    assert balance == Decimal("300") - int_settings.chat_min_charge
    if in_thread:
        assert env.calls.get("reply" if provider == "github" else "note_reply")
    if "summary" in body:
        edit = env.calls.get("pr_patch" if provider == "github" else "mr_put") or []
        assert any(
            "hootpr:summary:start" in (c.get("body") or c.get("description") or "") for c in edit
        )


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_bot_reply_loop_is_ignored(
    provider: str,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
) -> None:
    env = setup(db, provider, int_settings, crypto, make_wctx)
    bot = "hootpr-test[bot]" if provider == "github" else "hootpr-bot"
    await send(
        client,
        env,
        f"{env.mention} review — use `{env.mention} full review`",
        delivery=f"{provider}-loop",
        author=bot,
    )
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env)
    assert env.replies == [] and db.execute(select(ChatMessage)).first() is None


LEARN_BASE = {"src/cli.py": "def main():\n    return 0\n"}
LEARN_HEAD: dict[str, str | None] = {
    "src/cli.py": "def main():\n    print('starting')\n    return 0\n"
}
PRINT_NIT = {
    "path": "src/cli.py",
    "start_line": None,
    "end_line": 2,
    "severity": "minor",
    "category": "maintainability",
    "title": "Use logging instead of print",
    "confidence": 0.9,
}
TEACH = "In this repo print() is the CLI output channel; do not flag print statements."


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_learning_taught_in_chat_changes_the_next_review(
    provider: str,
    client: httpx.AsyncClient,
    app: FastAPI,
    db: Session,
    int_settings: Settings,
    crypto: Crypto,
    make_wctx: Callable[..., WorkerContext],
    tmp_path: Path,
) -> None:
    git = make_git_repo(tmp_path / "src", LEARN_BASE, LEARN_HEAD)
    env = setup(
        db,
        provider,
        int_settings,
        crypto,
        make_wctx,
        head=git.head_sha,
        base=git.base_sha,
        files=git.files,
    )
    env.ctx.sandboxes = LocalSandboxManager(
        write_stub_tools(tmp_path / "tools"),
        base_dir=tmp_path,
        remote_map=lambda url: str(git.path),
    )
    env.fake.findings = [PRINT_NIT]
    env.fake.suppress = {"Use logging instead of print": "print"}
    # 1. the developer replies in HootPR's review thread; the chat agent records the preference
    env.fake.chat_turns = [
        [tool_call("add_learning", {"text": TEACH, "scope": "repo", "path_glob": None})]
    ]
    await send(
        client,
        env,
        "we use print on purpose in the CLI",
        delivery=f"{provider}-teach",
        in_thread=True,
    )
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env)
    learning = db.execute(select(Learning)).scalar_one()
    assert learning.text == TEACH and learning.embedding is not None
    assert any("✏️ Learnings added" in r for r in env.replies)
    # 2. `full review` runs with the learning injected, and the nitpick is no longer raised
    await send(client, env, f"{env.mention} full review", delivery=f"{provider}-rerun")
    with respx.mock(assert_all_called=False) as mock:
        routes(mock, env)
        drain(app, env, run_reviews=True)
    review = db.execute(select(Review).where(Review.trigger == "command_full")).scalar_one()
    assert review.status == "completed", review.error
    assert any("<team_learnings>" in t and TEACH in t for t in env.fake.user_texts["agent"])
    titles = {
        f.title for f in db.execute(select(Finding).where(Finding.review_id == review.id)).scalars()
    }
    assert "Use logging instead of print" not in titles
    walkthroughs = [r for r in env.replies if "hootpr:walkthrough" in r]
    assert walkthroughs and "🧠 Learnings used:** 1" in walkthroughs[-1]


def test_same_review_without_the_learning_raises_the_nit(
    db: Session,
    local_platform: LocalPlatform,
    make_wctx: Callable[..., WorkerContext],
    tmp_path: Path,
) -> None:
    """Control: identical PR, fake and pipeline without the learning → the nitpick is kept, so the
    difference in the test above is caused by the learning alone."""
    git = make_git_repo(tmp_path / "src", LEARN_BASE, LEARN_HEAD)
    org = make_org(db, balance="300")
    make_repo(db, org, make_installation(db, org))
    local_platform.add_pull_request(
        REF,
        PlatformPR(
            7, "CLI", "", "alice", "open", False, "main", "f", git.base_sha, git.head_sha, (), ""
        ),
        git.files,
    )
    local_platform.register_repo_path(REF, git.path)
    fake = EngineFakeLLM()
    fake.findings = [PRINT_NIT]
    fake.suppress = {"Use logging instead of print": "print"}
    ctx = make_wctx(
        sandboxes=LocalSandboxManager(write_stub_tools(tmp_path / "tools"), base_dir=tmp_path),
        llm=lambda: make_test_gateway(fake)[0],
    )
    handle_pr_event(ctx, pr_event(head=git.head_sha))
    run_queued(ctx)
    f = db.execute(select(Finding)).scalar_one()
    assert (f.title, f.judge_verdict) == ("Use logging instead of print", "keep")
    assert not any("<team_learnings>" in t for t in fake.user_texts["agent"])
