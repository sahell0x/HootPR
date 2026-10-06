import base64
import json

import httpx
import pytest
import respx

from app.events.models import PipelineFailed
from app.platforms.base import RepoRef
from app.platforms.finishing import FileChange, PushRejected, branch_name, tail_text
from app.platforms.github.app_auth import GitHubAppAuth
from app.platforms.github.platform import GitHubPlatform
from app.platforms.github.webhooks import parse_event
from app.platforms.gitlab.finishing import commit_actions
from app.platforms.gitlab.platform import GitLabPlatform
from app.platforms.gitlab.webhooks import parse_event as parse_gitlab
from tests.fakes.kv import DictKV

GH = "https://api.github.com"
GL = "https://gitlab.com/api/v4"
GH_REPO = RepoRef("github", "1001", "acme/web")
GL_REPO = RepoRef("gitlab", "2002", "acme-group/api")
PARENT, TREE = "p" * 40, "t" * 40


@pytest.fixture
def gh(rsa_pem: str) -> GitHubPlatform:
    auth = GitHubAppAuth("1", rsa_pem, DictKV({"gh:insttoken:42": "ghs_test"}), GH)
    return GitHubPlatform(auth, 42)


def _git_data_mocks() -> dict[str, respx.Route]:
    return {
        "base": respx.get(f"{GH}/repos/acme/web/git/commits/{PARENT}").mock(
            return_value=httpx.Response(200, json={"tree": {"sha": TREE}})
        ),
        "blob": respx.post(f"{GH}/repos/acme/web/git/blobs").mock(
            return_value=httpx.Response(201, json={"sha": "b" * 40})
        ),
        "tree": respx.post(f"{GH}/repos/acme/web/git/trees").mock(
            return_value=httpx.Response(201, json={"sha": "n" * 40})
        ),
        "commit": respx.post(f"{GH}/repos/acme/web/git/commits").mock(
            return_value=httpx.Response(201, json={"sha": "c" * 40})
        ),
    }


@respx.mock
def test_github_push_commit_fast_forward(gh: GitHubPlatform) -> None:
    m = _git_data_mocks()
    ref = respx.patch(f"{GH}/repos/acme/web/git/refs/heads/feat").mock(
        return_value=httpx.Response(200, json={})
    )
    sha = gh.push_commit(
        GH_REPO,
        "feat",
        PARENT,
        "msg",
        [FileChange("a.py", b"x = 1\n"), FileChange("old.py", None)],
        extra_parents=["m" * 40],
    )
    assert sha == "c" * 40
    blob = json.loads(m["blob"].calls[0].request.content)
    assert base64.b64decode(blob["content"]) == b"x = 1\n"
    tree = json.loads(m["tree"].calls[0].request.content)
    assert tree["base_tree"] == TREE
    assert {"path": "old.py", "mode": "100644", "type": "blob", "sha": None} in tree["tree"]
    commit = json.loads(m["commit"].calls[0].request.content)
    assert commit["parents"] == [PARENT, "m" * 40]
    assert json.loads(ref.calls[0].request.content) == {"sha": "c" * 40, "force": False}


@respx.mock
def test_github_push_rejected_when_branch_moved(gh: GitHubPlatform) -> None:
    _git_data_mocks()
    respx.patch(f"{GH}/repos/acme/web/git/refs/heads/feat").mock(
        return_value=httpx.Response(422, json={"message": "Update is not a fast forward"})
    )
    with pytest.raises(PushRejected):
        gh.push_commit(GH_REPO, "feat", PARENT, "msg", [FileChange("a.py", b"x")])


@respx.mock
def test_github_stacked_branch_and_pr(gh: GitHubPlatform) -> None:
    _git_data_mocks()
    created = respx.post(f"{GH}/repos/acme/web/git/refs").mock(
        return_value=httpx.Response(201, json={})
    )
    pulls = respx.post(f"{GH}/repos/acme/web/pulls").mock(
        return_value=httpx.Response(
            201,
            json={
                "number": 9,
                "title": "t",
                "html_url": "https://github.com/acme/web/pull/9",
                "user": {"login": "hootpr[bot]"},
                "state": "open",
                "base": {"ref": "feat", "sha": PARENT},
                "head": {"ref": "hootpr/docstrings-7-abc", "sha": "c" * 40},
            },
        )
    )
    gh.push_commit(GH_REPO, "hootpr/docstrings-7-abc", PARENT, "m", [FileChange("a", b"")],
                   create_branch=True)  # fmt: skip
    assert (
        json.loads(created.calls[0].request.content)["ref"] == "refs/heads/hootpr/docstrings-7-abc"
    )
    pr = gh.open_pull_request(GH_REPO, "hootpr/docstrings-7-abc", "feat", "t", "body")
    assert pr.number == 9 and pr.base_ref == "feat"
    assert json.loads(pulls.calls[0].request.content)["base"] == "feat"


@respx.mock
def test_github_ci_logs_follow_redirect_and_keep_tail(gh: GitHubPlatform) -> None:
    respx.get(f"{GH}/repos/acme/web/actions/runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {"id": 5, "name": "CI", "conclusion": "failure"},
                    {"id": 6, "name": "Lint", "conclusion": "success"},
                ]
            },
        )
    )
    respx.get(f"{GH}/repos/acme/web/actions/runs/5/jobs").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 77,
                        "name": "test",
                        "conclusion": "failure",
                        "html_url": "u",
                        "steps": [{"name": "pytest", "conclusion": "failure"}],
                    },
                    {"id": 78, "name": "build", "conclusion": "success"},
                ]
            },
        )
    )
    respx.get(f"{GH}/repos/acme/web/actions/jobs/77/logs").mock(
        return_value=httpx.Response(302, headers={"location": "https://logs.example/77"})
    )
    respx.get("https://logs.example/77").mock(
        return_value=httpx.Response(200, content=b"x" * 5000 + b"\nFAILED test_a")
    )
    logs = gh.get_ci_logs(GH_REPO, "h" * 40, max_log_kb=1)
    assert len(logs) == 1 and logs[0].failed_step == "pytest" and logs[0].run_id == "5"
    assert logs[0].log_tail.endswith("FAILED test_a") and "truncated" in logs[0].log_tail


@respx.mock
def test_gitlab_push_checks_tip_then_commits() -> None:
    gl = GitLabPlatform("glpat-bot", bot_user_id=9)
    respx.get(f"{GL}/projects/2002/repository/branches/fix%2Fp").mock(
        return_value=httpx.Response(200, json={"commit": {"id": PARENT}})
    )
    commits = respx.post(f"{GL}/projects/2002/repository/commits").mock(
        return_value=httpx.Response(201, json={"id": "c" * 40})
    )
    sha = gl.push_commit(GL_REPO, "fix/p", PARENT, "msg", [FileChange("n.py", b"n", is_new=True)])
    body = json.loads(commits.calls[0].request.content)
    assert sha == "c" * 40 and body["branch"] == "fix/p" and "start_sha" not in body
    assert body["actions"][0]["action"] == "create"


@respx.mock
def test_gitlab_push_rejected_when_tip_moved() -> None:
    gl = GitLabPlatform("glpat-bot", bot_user_id=9)
    respx.get(f"{GL}/projects/2002/repository/branches/fix%2Fp").mock(
        return_value=httpx.Response(200, json={"commit": {"id": "z" * 40}})
    )
    with pytest.raises(PushRejected):
        gl.push_commit(GL_REPO, "fix/p", PARENT, "msg", [FileChange("a", b"x")])


def test_commit_actions_and_helpers() -> None:
    acts = commit_actions(
        [FileChange("a", b"1"), FileChange("b", None), FileChange("c", b"2", executable=True,
                                                                  is_new=True)]
    )  # fmt: skip
    assert [a["action"] for a in acts] == ["update", "delete", "create"]
    assert acts[2]["execute_filemode"] is True
    assert branch_name("unit tests", 12, "0192ab34-cdef") == "hootpr/unit-tests-12-0192ab34"
    assert tail_text("short", 1) == "short"


def test_workflow_run_failure_is_parsed() -> None:
    payload = {
        "action": "completed",
        "installation": {"id": 42},
        "repository": {"id": 1001, "full_name": "acme/web"},
        "workflow_run": {
            "id": 555,
            "conclusion": "failure",
            "head_sha": "h" * 40,
            "head_branch": "feat",
            "html_url": "https://github.com/acme/web/actions/runs/555",
            "pull_requests": [{"number": 7, "base": {"repo": {"id": 1001}}}],
        },
    }
    ev = parse_event("workflow_run", payload, "d-1")
    assert isinstance(ev, PipelineFailed)
    assert ev.pr_number == 7 and ev.run_id == "555" and ev.sha == "h" * 40
    payload["workflow_run"]["conclusion"] = "success"  # type: ignore[index]
    assert parse_event("workflow_run", payload, "d-2") is None


def test_gitlab_pipeline_failure_carries_run() -> None:
    ev = parse_gitlab(
        "Pipeline Hook",
        {
            "object_kind": "pipeline",
            "object_attributes": {"id": 31, "status": "failed", "sha": "h" * 40, "ref": "fix/p"},
            "merge_request": {"iid": 3},
            "project": {"id": 2002, "path_with_namespace": "acme-group/api"},
        },
        "d-3",
    )
    assert isinstance(ev, PipelineFailed) and ev.run_id == "31" and ev.pr_number == 3
