import json

import httpx
import pytest
import respx

from app.platforms.base import InlineComment, RepoRef
from app.platforms.github.app_auth import GitHubAppAuth
from app.platforms.github.platform import GitHubPlatform
from tests.fakes.kv import DictKV

API = "https://api.github.com"
REPO = RepoRef("github", "1001", "acme/web")


@pytest.fixture
def gh(rsa_pem: str) -> GitHubPlatform:
    auth = GitHubAppAuth("1", rsa_pem, DictKV({"gh:insttoken:42": "ghs_test"}), API)
    return GitHubPlatform(auth, 42)


PR_JSON = {
    "number": 7,
    "title": "Add rate limit",
    "body": None,
    "state": "closed",
    "draft": False,
    "merged_at": "2026-09-01T00:00:00Z",
    "html_url": "https://github.com/acme/web/pull/7",
    "user": {"login": "alice"},
    "labels": [{"name": "backend"}],
    "base": {"ref": "main", "sha": "b" * 40},
    "head": {"ref": "feat", "sha": "h" * 40},
}


@respx.mock
def test_get_pull_request_maps_fields(gh: GitHubPlatform) -> None:
    respx.get(f"{API}/repos/acme/web/pulls/7").mock(return_value=httpx.Response(200, json=PR_JSON))
    pr = gh.get_pull_request(REPO, 7)
    assert pr.state == "merged" and pr.body == "" and pr.labels == ("backend",)
    assert pr.head_sha == "h" * 40 and pr.author_username == "alice"


@respx.mock
def test_get_diff_pages_and_binary(gh: GitHubPlatform) -> None:
    respx.get(f"{API}/repos/acme/web/pulls/7/files").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "filename": "a.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "patch": "@@ -1 +1 @@\n-a\n+b",
                },
                {"filename": "logo.png", "status": "added", "additions": 0, "deletions": 0},
                {
                    "filename": "new.py",
                    "previous_filename": "old.py",
                    "status": "renamed",
                    "additions": 0,
                    "deletions": 0,
                    "patch": "",
                },
            ],
        )
    )
    files = gh.get_diff(REPO, 7)
    assert [f.path for f in files] == ["a.py", "logo.png", "new.py"]
    assert files[0].additions == 1 and files[0].changed_new_lines() == {1}
    assert files[1].is_binary is True
    assert files[2].status == "renamed" and files[2].old_path == "old.py"


@respx.mock
def test_get_diff_between_shas_uses_compare(gh: GitHubPlatform) -> None:
    respx.get(f"{API}/repos/acme/web/compare/aaa...bbb").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {"filename": "a.py", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"}
                ]
            },
        )
    )
    assert gh.get_diff(REPO, 7, base_sha="aaa", head_sha="bbb")[0].path == "a.py"


@respx.mock
def test_get_file(gh: GitHubPlatform) -> None:
    respx.get(f"{API}/repos/acme/web/contents/.hootpr.yaml", params={"ref": "main"}).mock(
        return_value=httpx.Response(200, text="language: en-US\n")
    )
    respx.get(f"{API}/repos/acme/web/contents/missing.yaml").mock(return_value=httpx.Response(404))
    assert gh.get_file(REPO, ".hootpr.yaml", "main") == "language: en-US\n"
    assert gh.get_file(REPO, "missing.yaml", "main") is None


@respx.mock
def test_upsert_comment_creates_then_updates(gh: GitHubPlatform) -> None:
    list_route = respx.get(f"{API}/repos/acme/web/issues/7/comments")
    list_route.mock(return_value=httpx.Response(200, json=[{"id": 1, "body": "other"}]))
    create = respx.post(f"{API}/repos/acme/web/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 99})
    )
    assert gh.upsert_comment(REPO, 7, "<!-- hootpr:walkthrough -->", "hello") == "99"
    assert json.loads(create.calls[0].request.content)["body"].startswith(
        "<!-- hootpr:walkthrough -->"
    )
    list_route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 99,
                    "body": "<!-- hootpr:walkthrough -->\nhello",
                    "user": {"login": "hootpr[bot]", "type": "Bot"},
                }
            ],
        )
    )
    patch = respx.patch(f"{API}/repos/acme/web/issues/comments/99").mock(
        return_value=httpx.Response(200, json={"id": 99})
    )
    assert gh.upsert_comment(REPO, 7, "<!-- hootpr:walkthrough -->", "bye") == "99"
    assert patch.call_count == 1


@respx.mock
def test_upsert_comment_ignores_marker_in_other_authors_comments(gh: GitHubPlatform) -> None:
    """A user quoting the marker must not make HootPR try (and fail) to edit their comment."""
    respx.get(f"{API}/repos/acme/web/issues/7/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 5,
                    "body": "> <!-- hootpr:walkthrough -->\nquoted",
                    "user": {"login": "mallory", "type": "User"},
                },
                {
                    "id": 6,
                    "body": "<!-- hootpr:walkthrough -->",
                    "user": {"login": "other-app[bot]", "type": "Bot"},
                },
            ],
        )
    )
    patch = respx.patch(url__regex=rf"{API}/repos/acme/web/issues/comments/\d+")
    create = respx.post(f"{API}/repos/acme/web/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 100})
    )
    assert gh.upsert_comment(REPO, 7, "<!-- hootpr:walkthrough -->", "hi") == "100"
    assert patch.call_count == 0 and create.call_count == 1


@respx.mock
def test_post_review_is_one_call_with_suggestions(gh: GitHubPlatform) -> None:
    create = respx.post(f"{API}/repos/acme/web/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json={"id": 555})
    )
    respx.get(f"{API}/repos/acme/web/pulls/7/reviews/555/comments").mock(
        return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    )
    ids = gh.post_review(
        REPO,
        7,
        "h" * 40,
        "summary",
        [
            InlineComment("a.py", 10, "Use a constant", start_line=8, suggestion="X = 1"),
            InlineComment("b.py", 3, "Typo"),
        ],
    )
    assert ids == ["1", "2"] and create.call_count == 1
    body = json.loads(create.calls[0].request.content)
    assert body["event"] == "COMMENT" and body["commit_id"] == "h" * 40
    c0 = body["comments"][0]
    assert c0 == {
        "path": "a.py",
        "line": 10,
        "side": "RIGHT",
        "start_line": 8,
        "start_side": "RIGHT",
        "body": "Use a constant\n\n```suggestion\nX = 1\n```",
    }
    assert "start_line" not in body["comments"][1]


@respx.mock
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("in_progress", {"status": "in_progress"}),
        ("success", {"status": "completed", "conclusion": "success"}),
        ("neutral", {"status": "completed", "conclusion": "neutral"}),
    ],
)
def test_set_status_creates_check_run(
    gh: GitHubPlatform, state: str, expected: dict[str, str]
) -> None:
    route = respx.post(f"{API}/repos/acme/web/check-runs").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    gh.set_status(REPO, "h" * 40, state, "Title", "Summary")  # type: ignore[arg-type]
    body = json.loads(route.calls[0].request.content)
    assert body["name"] == "HootPR" and body["head_sha"] == "h" * 40
    assert body["output"] == {"title": "Title", "summary": "Summary"}
    for k, v in expected.items():
        assert body[k] == v


@respx.mock
def test_update_pr_description_and_clone_credentials(gh: GitHubPlatform) -> None:
    respx.get(f"{API}/repos/acme/web/pulls/7").mock(return_value=httpx.Response(200, json=PR_JSON))
    patch = respx.patch(f"{API}/repos/acme/web/pulls/7").mock(
        return_value=httpx.Response(200, json={})
    )
    gh.update_pr_description(REPO, 7, "hootpr:summary", "Sum")
    assert (
        "<!-- hootpr:summary:start -->\nSum" in json.loads(patch.calls[0].request.content)["body"]
    )
    creds = gh.clone_credentials(REPO)
    assert creds.url == "https://github.com/acme/web.git"
    assert creds.username == "x-access-token" and creds.token == "ghs_test"


@respx.mock
def test_reply_reaction_resolve(gh: GitHubPlatform) -> None:
    reply = respx.post(f"{API}/repos/acme/web/pulls/7/comments/321/replies").mock(
        return_value=httpx.Response(201, json={"id": 400})
    )
    react = respx.post(f"{API}/repos/acme/web/issues/comments/555/reactions").mock(
        return_value=httpx.Response(201, json={})
    )
    gql = respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json={"data": {}}))
    assert gh.reply_to_comment(REPO, 7, "321", "ok") == "400"
    gh.add_reaction(REPO, "555", "eyes")
    gh.resolve_thread(REPO, 7, "PRRT_abc")
    assert json.loads(react.calls[0].request.content) == {"content": "eyes"}
    assert json.loads(gql.calls[0].request.content)["variables"] == {"id": "PRRT_abc"}
    assert reply.call_count == 1


@respx.mock
def test_post_review_request_changes_event(gh: GitHubPlatform) -> None:
    route = respx.post(f"{API}/repos/acme/web/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json={"id": 99})
    )
    respx.get(f"{API}/repos/acme/web/pulls/7/reviews/99/comments").mock(
        return_value=httpx.Response(200, json=[{"id": 5}])
    )
    ids = gh.post_review(
        REPO, 7, "h" * 40, "summary", [InlineComment("a.py", 3, "body")], event="REQUEST_CHANGES"
    )
    assert ids == ["5"]
    assert json.loads(route.calls[0].request.content)["event"] == "REQUEST_CHANGES"


@respx.mock
def test_post_review_422_propagates_for_the_caller_fallback(gh: GitHubPlatform) -> None:
    from app.platforms.base import PlatformError

    respx.post(f"{API}/repos/acme/web/pulls/7/reviews").mock(
        return_value=httpx.Response(422, json={"message": "line must be part of the diff"})
    )
    with pytest.raises(PlatformError) as exc:
        gh.post_review(REPO, 7, "h" * 40, None, [InlineComment("a.py", 99, "x")])
    assert exc.value.status_code == 422


THREADS = {
    "data": {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "PRRT_1",
                            "isResolved": True,
                            "comments": {"nodes": [{"databaseId": 501}]},
                        },
                        {
                            "id": "PRRT_2",
                            "isResolved": False,
                            "comments": {"nodes": [{"databaseId": 601}]},
                        },
                    ],
                }
            }
        }
    }
}


@respx.mock
def test_list_comments_reports_thread_resolution(gh: GitHubPlatform) -> None:
    respx.get(f"{API}/repos/acme/web/issues/7/comments").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{API}/repos/acme/web/pulls/7/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 501,
                    "user": {"login": "hootpr[bot]"},
                    "body": "x",
                    "path": "a.py",
                    "line": 2,
                },
                {
                    "id": 502,
                    "user": {"login": "bob"},
                    "body": "y",
                    "path": "a.py",
                    "line": 2,
                    "in_reply_to_id": 501,
                },
                {
                    "id": 601,
                    "user": {"login": "hootpr[bot]"},
                    "body": "z",
                    "path": "b.py",
                    "line": 1,
                },
            ],
        )
    )
    gql = respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=THREADS))
    got = {c.id: (c.thread_ref, c.resolved) for c in gh.list_comments(REPO, 7)}
    assert got == {"501": ("501", True), "502": ("501", True), "601": ("601", False)}
    assert json.loads(gql.calls[0].request.content)["variables"] == {
        "owner": "acme",
        "name": "web",
        "number": 7,
        "after": None,
    }


@respx.mock
def test_list_comments_without_review_comments_skips_graphql(gh: GitHubPlatform) -> None:
    respx.get(f"{API}/repos/acme/web/issues/7/comments").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "user": {"login": "bob"}, "body": "hi"}])
    )
    respx.get(f"{API}/repos/acme/web/pulls/7/comments").mock(
        return_value=httpx.Response(200, json=[])
    )
    [c] = gh.list_comments(REPO, 7)
    assert c.resolved is None


@respx.mock
def test_resolve_thread_by_root_comment_id(gh: GitHubPlatform) -> None:
    gql = respx.post(f"{API}/graphql").mock(
        side_effect=[
            httpx.Response(200, json=THREADS),
            httpx.Response(
                200,
                json={
                    "data": {
                        "resolveReviewThread": {"thread": {"id": "PRRT_2", "isResolved": True}}
                    }
                },
            ),
        ]
    )
    gh.resolve_thread(REPO, 7, "601")
    assert json.loads(gql.calls[1].request.content)["variables"] == {"id": "PRRT_2"}


@respx.mock
def test_resolve_thread_accepts_node_id_and_rejects_unknown(gh: GitHubPlatform) -> None:
    from app.platforms.base import NotFoundError

    gql = respx.post(f"{API}/graphql").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"resolveReviewThread": {"thread": {}}}}),
            httpx.Response(200, json=THREADS),
        ]
    )
    gh.resolve_thread(REPO, 7, "PRRT_9")
    assert json.loads(gql.calls[0].request.content)["variables"] == {"id": "PRRT_9"}
    with pytest.raises(NotFoundError):
        gh.resolve_thread(REPO, 7, "999")


@respx.mock
def test_approve_title_and_review_comment_reaction(gh: GitHubPlatform) -> None:
    review = respx.post(f"{API}/repos/acme/web/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    gh.post_review(REPO, 7, "h" * 40, "All resolved", [], event="APPROVE")
    assert json.loads(review.calls[0].request.content)["event"] == "APPROVE"
    title = respx.patch(f"{API}/repos/acme/web/pulls/7").mock(
        return_value=httpx.Response(200, json={})
    )
    gh.update_pr_title(REPO, 7, "Add rate limiting")
    assert json.loads(title.calls[0].request.content) == {"title": "Add rate limiting"}
    react = respx.post(f"{API}/repos/acme/web/pulls/comments/9001/reactions").mock(
        return_value=httpx.Response(201, json={})
    )
    gh.add_reaction(REPO, "review:9001", "eyes")
    assert react.called


@respx.mock
def test_can_write_uses_collaborator_permission(gh: GitHubPlatform) -> None:
    from app.platforms.base import PlatformError

    base = f"{API}/repos/acme/web/collaborators"
    respx.get(f"{base}/alice/permission").mock(
        return_value=httpx.Response(200, json={"permission": "write", "role_name": "maintain"})
    )
    respx.get(f"{base}/eve/permission").mock(
        return_value=httpx.Response(200, json={"permission": "read", "role_name": "triage"})
    )
    respx.get(f"{base}/ghost/permission").mock(return_value=httpx.Response(404, json={}))
    respx.get(f"{base}/boom/permission").mock(return_value=httpx.Response(500, json={}))
    assert gh.can_write(REPO, "alice") is True
    assert gh.can_write(REPO, "eve") is False
    assert gh.can_write(REPO, "ghost") is False
    with pytest.raises(PlatformError):
        gh.can_write(REPO, "boom")


@respx.mock
def test_resolve_thread_lists_threads_once_per_instance(gh: GitHubPlatform) -> None:
    ok = httpx.Response(200, json={"data": {"resolveReviewThread": {"thread": {}}}})
    gql = respx.post(f"{API}/graphql").mock(side_effect=[httpx.Response(200, json=THREADS), ok, ok])
    gh.resolve_thread(REPO, 7, "601")
    gh.resolve_thread(REPO, 7, "501")
    assert gql.call_count == 3  # one listing + two mutations
    assert json.loads(gql.calls[2].request.content)["variables"] == {"id": "PRRT_1"}
