import json

import httpx
import pytest
import respx

from app.platforms.base import InlineComment, RepoRef
from app.platforms.gitlab.platform import GitLabPlatform

API = "https://gitlab.com/api/v4"
REPO = RepoRef("gitlab", "2002", "acme-group/api")
MR = {
    "iid": 3,
    "title": "Fix pagination",
    "description": "Closes #1",
    "state": "opened",
    "draft": False,
    "source_branch": "fix/p",
    "target_branch": "main",
    "sha": "h" * 40,
    "web_url": "https://gitlab.com/acme-group/api/-/merge_requests/3",
    "author": {"username": "carol"},
    "labels": ["bug"],
    "diff_refs": {"base_sha": "b" * 40, "head_sha": "h" * 40, "start_sha": "s" * 40},
}


@pytest.fixture
def gl() -> GitLabPlatform:
    return GitLabPlatform("glpat-bot", bot_user_id=9)


@respx.mock
def test_get_pull_request(gl: GitLabPlatform) -> None:
    route = respx.get(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json=MR)
    )
    pr = gl.get_pull_request(REPO, 3)
    assert pr.state == "open" and pr.base_sha == "b" * 40 and pr.head_sha == "h" * 40
    assert pr.labels == ("bug",) and pr.author_username == "carol"
    assert route.calls[0].request.headers["PRIVATE-TOKEN"] == "glpat-bot"


@respx.mock
@pytest.mark.parametrize(
    ("raw", "files"), [("7", 7), ("1000+", 1000), (12, 12), (None, None), ("n/a", None)]
)
def test_get_pull_request_sizes_hold_from_changes_count(
    gl: GitLabPlatform, raw: object, files: int | None
) -> None:
    from decimal import Decimal

    from app.billing.pricing import estimate_review_hold
    from app.settings import Settings

    respx.get(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json={**MR, "changes_count": raw})
    )
    pr = gl.get_pull_request(REPO, 3)
    assert pr.changed_files == files and pr.changed_lines is None
    settings = Settings(_env_file=None)  # type: ignore[arg-type]
    hold = estimate_review_hold(pr.changed_lines, pr.changed_files, settings)
    if files == 7:  # 100 + 7 * 40 lines * 0.4 + 7 * 5 = 247
        assert hold == Decimal("247")
    elif files is None or files == 1000:
        assert hold == Decimal("1000")


@respx.mock
def test_get_diff(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/merge_requests/3/diffs").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "new_path": "a.py",
                    "old_path": "a.py",
                    "diff": "@@ -1 +1,2 @@\n-a\n+b\n+c\n",
                    "new_file": False,
                    "renamed_file": False,
                    "deleted_file": False,
                },
                {
                    "new_path": "img.png",
                    "old_path": "img.png",
                    "diff": "",
                    "new_file": True,
                    "renamed_file": False,
                    "deleted_file": False,
                },
            ],
        )
    )
    files = gl.get_diff(REPO, 3)
    assert (files[0].additions, files[0].deletions) == (2, 1)
    assert files[1].status == "added" and files[1].is_binary


@respx.mock
def test_get_diff_between_shas_uses_compare(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/repository/compare").mock(
        return_value=httpx.Response(
            200,
            json={
                "diffs": [
                    {
                        "new_path": "x",
                        "old_path": "x",
                        "diff": "@@ -1 +1 @@\n-a\n+b\n",
                        "new_file": False,
                        "renamed_file": False,
                        "deleted_file": False,
                    }
                ]
            },
        )
    )
    assert gl.get_diff(REPO, 3, base_sha="a", head_sha="b")[0].path == "x"


@respx.mock
def test_get_file_encodes_path(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/repository/files/.hootpr.yaml/raw").mock(
        return_value=httpx.Response(200, text="poem: true\n")
    )
    respx.get(f"{API}/projects/2002/repository/files/sub%2Fnope.yaml/raw").mock(
        return_value=httpx.Response(404)
    )
    assert gl.get_file(REPO, ".hootpr.yaml", "main") == "poem: true\n"
    assert gl.get_file(REPO, "sub/nope.yaml", "main") is None


@respx.mock
def test_upsert_comment(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/merge_requests/3/notes").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 49,
                    "body": "> <!-- hootpr:walkthrough -->",
                    "system": False,
                    "author": {"id": 1, "username": "mallory"},
                },
                {
                    "id": 50,
                    "body": "<!-- hootpr:walkthrough -->\nold",
                    "system": False,
                    "author": {"id": 9, "username": "hootpr-bot"},
                },
            ],
        )
    )
    put = respx.put(f"{API}/projects/2002/merge_requests/3/notes/50").mock(
        return_value=httpx.Response(200, json={"id": 50})
    )
    assert gl.upsert_comment(REPO, 3, "<!-- hootpr:walkthrough -->", "new") == "50"
    assert json.loads(put.calls[0].request.content)["body"] == "<!-- hootpr:walkthrough -->\nnew"


@respx.mock
def test_upsert_comment_learns_bot_id_and_skips_foreign_notes() -> None:
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json={"id": 9}))
    respx.get(f"{API}/projects/2002/merge_requests/3/notes").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 49,
                    "body": "<!-- hootpr:walkthrough -->",
                    "system": False,
                    "author": {"id": 1, "username": "mallory"},
                }
            ],
        )
    )
    put = respx.put(url__regex=rf"{API}/projects/2002/merge_requests/3/notes/\d+")
    post = respx.post(f"{API}/projects/2002/merge_requests/3/notes").mock(
        return_value=httpx.Response(201, json={"id": 51})
    )
    assert (
        GitLabPlatform("glpat-bot").upsert_comment(REPO, 3, "<!-- hootpr:walkthrough -->", "x")
        == "51"
    )
    assert put.call_count == 0 and post.call_count == 1


@respx.mock
def test_post_review_creates_positioned_discussions(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json=MR)
    )
    disc = respx.post(f"{API}/projects/2002/merge_requests/3/discussions").mock(
        return_value=httpx.Response(201, json={"id": "d1"})
    )
    note = respx.post(f"{API}/projects/2002/merge_requests/3/notes").mock(
        return_value=httpx.Response(201, json={"id": 9})
    )
    ids = gl.post_review(
        REPO,
        3,
        "h" * 40,
        "summary",
        [InlineComment("a.py", 12, "Use X", start_line=10, suggestion="X")],
    )
    assert ids == ["d1"] and note.call_count == 1
    body = json.loads(disc.calls[0].request.content)
    assert body["position"] == {
        "position_type": "text",
        "base_sha": "b" * 40,
        "start_sha": "s" * 40,
        "head_sha": "h" * 40,
        "new_path": "a.py",
        "old_path": "a.py",
        "new_line": 12,
    }
    assert body["body"].endswith("```suggestion:-2+0\nX\n```")


@respx.mock
@pytest.mark.parametrize(
    ("state", "gl_state"),
    [
        ("queued", "pending"),
        ("in_progress", "running"),
        ("success", "success"),
        ("failure", "failed"),
        ("neutral", "skipped"),
    ],
)
def test_set_status_maps_states(gl: GitLabPlatform, state: str, gl_state: str) -> None:
    route = respx.post(f"{API}/projects/2002/statuses/{'h' * 40}").mock(
        return_value=httpx.Response(201, json={})
    )
    gl.set_status(REPO, "h" * 40, state, "Title", "Summary")  # type: ignore[arg-type]
    body = json.loads(route.calls[0].request.content)
    assert body == {"state": gl_state, "name": "HootPR", "description": "Title"}


@respx.mock
def test_reply_resolve_react_and_clone(gl: GitLabPlatform) -> None:
    reply = respx.post(f"{API}/projects/2002/merge_requests/3/discussions/d1/notes").mock(
        return_value=httpx.Response(201, json={"id": 77})
    )
    resolve = respx.put(f"{API}/projects/2002/merge_requests/3/discussions/d1").mock(
        return_value=httpx.Response(200, json={})
    )
    award = respx.post(f"{API}/projects/2002/merge_requests/3/notes/88/award_emoji").mock(
        return_value=httpx.Response(201, json={})
    )
    assert gl.reply_to_comment(REPO, 3, "d1", "ok") == "77"
    gl.resolve_thread(REPO, 3, "d1")
    gl.add_reaction(REPO, "3:88", "+1")
    assert resolve.calls[0].request.url.params["resolved"] == "true"
    assert json.loads(award.calls[0].request.content) == {"name": "thumbsup"}
    assert reply.call_count == 1
    creds = gl.clone_credentials(REPO)
    assert creds.url == "https://gitlab.com/acme-group/api.git" and creds.username == "oauth2"


@respx.mock
def test_post_review_context_line_sends_old_and_new_line_and_old_path(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json=MR)
    )
    disc = respx.post(f"{API}/projects/2002/merge_requests/3/discussions").mock(
        return_value=httpx.Response(201, json={"id": "d1"})
    )
    ids = gl.post_review(
        REPO,
        3,
        "h" * 40,
        None,
        [InlineComment("new.py", 14, "Missing check", old_line=11, old_path="old.py")],
    )
    assert ids == ["d1"]
    pos = json.loads(disc.calls[0].request.content)["position"]
    assert pos["new_path"] == "new.py" and pos["old_path"] == "old.py"
    assert pos["new_line"] == 14 and pos["old_line"] == 11


@respx.mock
def test_post_review_skips_a_rejected_discussion(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json=MR)
    )
    respx.post(f"{API}/projects/2002/merge_requests/3/discussions").mock(
        side_effect=[
            httpx.Response(400, json={"message": "line_code can't be blank"}),
            httpx.Response(201, json={"id": "d2"}),
        ]
    )
    unapprove = respx.post(f"{API}/projects/2002/merge_requests/3/unapprove").mock(
        return_value=httpx.Response(403)
    )
    ids = gl.post_review(
        REPO,
        3,
        "h" * 40,
        None,
        [InlineComment("a.py", 99, "x"), InlineComment("a.py", 3, "y")],
        event="REQUEST_CHANGES",  # best-effort unapprove; the commit status carries the verdict
    )
    assert ids == ["", "d2"]
    assert unapprove.called


@respx.mock
def test_post_review_other_errors_still_raise(gl: GitLabPlatform) -> None:
    from app.platforms.base import PlatformError

    respx.get(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json=MR)
    )
    respx.post(f"{API}/projects/2002/merge_requests/3/discussions").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    with pytest.raises(PlatformError):
        gl.post_review(REPO, 3, "h" * 40, None, [InlineComment("a.py", 3, "y")])


@respx.mock
def test_list_comments_resolution_and_approve(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/merge_requests/3/discussions").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "d1",
                    "notes": [
                        {
                            "id": 1,
                            "author": {"username": "hootpr-bot"},
                            "body": "x",
                            "resolvable": True,
                            "resolved": True,
                            "position": {"new_path": "a.py", "new_line": 2},
                        }
                    ],
                },
                {
                    "id": "d2",
                    "notes": [
                        {"id": 2, "author": {"username": "dave"}, "body": "hi", "resolvable": False}
                    ],
                },
            ],
        )
    )
    got = {c.thread_ref: c.resolved for c in gl.list_comments(REPO, 3)}
    assert got == {"d1": True, "d2": None}
    respx.post(f"{API}/projects/2002/merge_requests/3/notes").mock(
        return_value=httpx.Response(201, json={"id": 5})
    )
    approve = respx.post(f"{API}/projects/2002/merge_requests/3/approve").mock(
        return_value=httpx.Response(401)
    )
    gl.post_review(REPO, 3, "h" * 40, "All resolved", [], event="APPROVE")  # 401 is tolerated
    assert approve.called
    unapprove = respx.post(f"{API}/projects/2002/merge_requests/3/unapprove").mock(
        return_value=httpx.Response(404)
    )
    gl.post_review(REPO, 3, "h" * 40, "Changes", [], event="REQUEST_CHANGES")
    assert unapprove.called


@respx.mock
def test_update_title(gl: GitLabPlatform) -> None:
    route = respx.put(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json=MR)
    )
    gl.update_pr_title(REPO, 3, "Fix pagination bounds")
    assert json.loads(route.calls[0].request.content) == {"title": "Fix pagination bounds"}


@respx.mock
def test_update_description_swaps_placeholder(gl: GitLabPlatform) -> None:
    respx.get(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json={**MR, "description": "Hi\n@hootpr summary"})
    )
    route = respx.put(f"{API}/projects/2002/merge_requests/3").mock(
        return_value=httpx.Response(200, json=MR)
    )
    gl.update_pr_description(REPO, 3, "hootpr:summary", "S", placeholder="@hootpr summary")
    body = json.loads(route.calls[0].request.content)["description"]
    assert body == "Hi\n<!-- hootpr:summary:start -->\nS\n<!-- hootpr:summary:end -->"


@respx.mock
def test_can_write_needs_developer_access(gl: GitLabPlatform) -> None:
    route = respx.get(f"{API}/projects/2002/members/all").mock(
        side_effect=lambda req: httpx.Response(
            200,
            json={
                "dev": [{"username": "dev", "access_level": 30}],
                "rep": [{"username": "rep", "access_level": 20}],
                "ann": [{"username": "annabel", "access_level": 40}],
            }.get(req.url.params["query"], []),
        )
    )
    assert gl.can_write(REPO, "dev") is True
    assert gl.can_write(REPO, "rep") is False
    assert gl.can_write(REPO, "ann") is False  # prefix match of another user
    assert gl.can_write(REPO, "nobody") is False
    assert route.calls[0].request.url.params["query"] == "dev"
