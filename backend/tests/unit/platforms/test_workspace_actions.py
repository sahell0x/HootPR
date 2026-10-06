import json

import httpx
import respx

from app.platforms.base import RepoRef
from app.platforms.local import LocalPlatform
from app.platforms.user import GitHubUserPlatform, GitLabUserPlatform
from app.platforms.workspace import UserReviewComment

GH = "https://api.github.com"
GL = "https://gitlab.example.com"
GH_REPO = RepoRef("github", "1", "acme/web")
GL_REPO = RepoRef("gitlab", "55", "acme/web")


@respx.mock
def test_github_user_review_uses_user_token_and_event() -> None:
    route = respx.post(f"{GH}/repos/acme/web/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json={"id": 99})
    )
    p = GitHubUserPlatform("ghu_user", api_url=GH, web_url="https://github.com")
    rid = p.submit_review(
        GH_REPO,
        7,
        "h" * 40,
        "REQUEST_CHANGES",
        "please fix",
        [UserReviewComment("a.py", 5, "bug", start_line=3)],
    )
    assert rid == "99"
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer ghu_user"
    body = json.loads(req.content)
    assert body["event"] == "REQUEST_CHANGES" and body["commit_id"] == "h" * 40
    assert body["comments"][0] == {
        "path": "a.py",
        "line": 5,
        "side": "RIGHT",
        "body": "bug",
        "start_line": 3,
        "start_side": "RIGHT",
    }


@respx.mock
def test_github_merge_success_and_head_moved() -> None:
    p = GitHubUserPlatform("ghu_user", api_url=GH, web_url="https://github.com")
    route = respx.put(f"{GH}/repos/acme/web/pulls/7/merge")
    route.mock(
        return_value=httpx.Response(200, json={"merged": True, "sha": "m1", "message": "ok"})
    )
    res = p.merge_pull_request(GH_REPO, 7, method="squash", sha="h1")
    assert res.merged and res.sha == "m1"
    assert json.loads(route.calls.last.request.content) == {"merge_method": "squash", "sha": "h1"}
    route.mock(return_value=httpx.Response(409, json={"message": "Head branch was modified"}))
    res = p.merge_pull_request(GH_REPO, 7, sha="old")
    assert not res.merged and "changed" in res.message


@respx.mock
def test_gitlab_user_approve_and_merge_use_bearer() -> None:
    notes = respx.post(f"{GL}/api/v4/projects/55/merge_requests/3/notes").mock(
        return_value=httpx.Response(201, json={"id": 11})
    )
    approve = respx.post(f"{GL}/api/v4/projects/55/merge_requests/3/approve").mock(
        return_value=httpx.Response(201, json={})
    )
    merge = respx.put(f"{GL}/api/v4/projects/55/merge_requests/3/merge").mock(
        return_value=httpx.Response(200, json={"state": "merged", "merge_commit_sha": "mc"})
    )
    p = GitLabUserPlatform("glo_user", base_url=GL)
    assert p.submit_review(GL_REPO, 3, "h", "APPROVE", "LGTM") == "11"
    assert notes.calls.last.request.headers["Authorization"] == "Bearer glo_user"
    assert "PRIVATE-TOKEN" not in approve.calls.last.request.headers
    res = p.merge_pull_request(GL_REPO, 3, method="squash", sha="h")
    assert res.merged and res.sha == "mc"
    assert json.loads(merge.calls.last.request.content) == {"squash": True, "sha": "h"}


def test_local_platform_records_user_actions() -> None:
    from app.platforms.base import PullRequest

    lp = LocalPlatform()
    pr = PullRequest(7, "t", "", "alice", "open", False, "main", "f", "b", "h", (), "u")
    lp.add_pull_request(GH_REPO, pr, [])
    lp.submit_review(GH_REPO, 7, "h", "APPROVE", "")
    assert lp.workspace.user_reviews[0].event == "APPROVE"
    assert not lp.merge_pull_request(GH_REPO, 7, sha="other").merged
    assert lp.merge_pull_request(GH_REPO, 7, sha="h").merged
    assert lp.get_pull_request(GH_REPO, 7).state == "merged"
