from pathlib import Path

import pytest

from app.platforms.base import InlineComment, NotFoundError, PullRequest, RepoRef
from app.platforms.diff import build_file_diff
from app.platforms.local import LocalPlatform

REPO = RepoRef("github", "1", "acme/web")
PR = PullRequest(7, "t", "b", "alice", "open", False, "main", "feat", "base1", "head1", (), "u")


@pytest.fixture
def lp() -> LocalPlatform:
    p = LocalPlatform()
    p.add_pull_request(REPO, PR, [build_file_diff("a.py", "@@ -1 +1 @@\n-a\n+b\n", "modified")])
    return p


def test_reads(lp: LocalPlatform) -> None:
    assert lp.get_pull_request(REPO, 7).title == "t"
    assert lp.get_diff(REPO, 7)[0].path == "a.py"
    with pytest.raises(NotFoundError):
        lp.get_pull_request(REPO, 99)
    lp.set_file(REPO, ".hootpr.yaml", "main", "language: en-US")
    assert lp.get_file(REPO, ".hootpr.yaml", "main") == "language: en-US"
    assert lp.get_file(REPO, "missing", "main") is None


def test_upsert_comment_edits_in_place(lp: LocalPlatform) -> None:
    first = lp.upsert_comment(REPO, 7, "<!-- m -->", "one")
    second = lp.upsert_comment(REPO, 7, "<!-- m -->", "two")
    assert first == second
    bodies = [c.body for c in lp.list_comments(REPO, 7)]
    assert bodies == ["<!-- m -->\ntwo"]


def test_status_review_description(lp: LocalPlatform) -> None:
    lp.set_status(REPO, "head1", "success", "Review completed", "ok")
    assert lp.statuses[-1].state == "success"
    ids = lp.post_review(REPO, 7, "head1", "sum", [InlineComment("a.py", 1, "fix")])
    assert len(ids) == 1 and lp.reviews[-1].comments[0].path == "a.py"
    lp.update_pr_description(REPO, 7, "hootpr:summary", "S")
    assert "hootpr:summary:start" in lp.descriptions[("1", 7)]


def test_fail_next(lp: LocalPlatform) -> None:
    lp.fail_next = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        lp.upsert_comment(REPO, 7, "<!-- m -->", "x")
    lp.upsert_comment(REPO, 7, "<!-- m -->", "x")  # only the next call fails


def test_register_repo_path_and_invalid_anchor_simulation(tmp_path: Path) -> None:
    from app.platforms.base import PlatformError

    lp = LocalPlatform()
    lp.add_pull_request(REPO, PR, [])
    assert lp.clone_credentials(REPO).url == "file:///local/acme/web.git"
    lp.register_repo_path(REPO, tmp_path)
    assert lp.clone_credentials(REPO).url == f"file://{tmp_path}"
    lp.invalid_anchors.add(("a.py", 9))
    with pytest.raises(PlatformError) as exc:
        lp.post_review(REPO, PR.number, "h", None, [InlineComment("a.py", 9, "x")])
    assert exc.value.status_code == 422
    assert lp.reviews == []
    gl = LocalPlatform(provider="gitlab")
    gl.add_pull_request(REPO, PR, [])
    gl.invalid_anchors.add(("a.py", 9))
    ids = gl.post_review(
        REPO, PR.number, "h", None, [InlineComment("a.py", 9, "x"), InlineComment("a.py", 3, "y")]
    )
    assert ids[0] == "" and ids[1] != ""
    assert gl.reviews[0].event == "COMMENT"
    assert [c.end_line for c in gl.reviews[0].comments] == [3]


def test_post_review_records_event(lp: LocalPlatform) -> None:
    lp.post_review(REPO, 7, "head1", None, [InlineComment("a.py", 1, "x")], event="REQUEST_CHANGES")
    assert lp.reviews[-1].event == "REQUEST_CHANGES"


def test_local_resolution_title_and_approval() -> None:
    lp = LocalPlatform()
    lp.add_pull_request(REPO, PR, [])
    [cid] = lp.post_review(REPO, 7, "h", None, [InlineComment("a.py", 1, "x")])
    assert [c.resolved for c in lp.list_comments(REPO, 7) if c.path] == [False]
    lp.resolve_thread(REPO, 7, cid)
    assert [c.resolved for c in lp.list_comments(REPO, 7) if c.path] == [True]
    lp.post_review(REPO, 7, "h", "ok", [], event="APPROVE")
    assert lp.approvals == [(REPO.provider_repo_id, 7)]
    assert lp.reviews[-1].event == "APPROVE"
    lp.update_pr_title(REPO, 7, "New title")
    assert lp.get_pull_request(REPO, 7).title == "New title"
    lp.descriptions[(REPO.provider_repo_id, 7)] = "x @hootpr summary"
    lp.update_pr_description(REPO, 7, "hootpr:summary", "S", placeholder="@hootpr summary")
    assert lp.get_pull_request(REPO, 7).body == (
        "x <!-- hootpr:summary:start -->\nS\n<!-- hootpr:summary:end -->"
    )


def test_local_can_write_defaults_to_true_and_is_configurable() -> None:
    from app.platforms.base import RepoRef

    lp = LocalPlatform()
    ref = RepoRef("github", "1", "a/b")
    assert lp.can_write(ref, "anyone") is True
    lp.readers.add("eve")
    assert lp.can_write(ref, "eve") is False
