import pytest

from app.events.models import (
    CommentCreated,
    InstallationChanged,
    PrEvent,
    ThreadStatusChanged,
    event_adapter,
)
from app.platforms.github.webhooks import parse_event, verify_signature
from tests.fixtures import fixture_bytes, load_fixture, sign_github


def test_verify_signature() -> None:
    body = fixture_bytes("github", "pull_request.opened")
    assert verify_signature("s3cret", body, sign_github("s3cret", body))
    assert not verify_signature("s3cret", body, sign_github("other", body))
    assert not verify_signature("s3cret", body, None)
    assert not verify_signature("", body, sign_github("", body))  # unset secret never verifies


def test_pull_request_opened() -> None:
    ev = parse_event("pull_request", load_fixture("github", "pull_request.opened"), "d-1")
    assert isinstance(ev, PrEvent)
    assert ev.kind == "pr_opened" and ev.installation_id == 42
    assert ev.repo.provider_repo_id == "1001" and ev.repo.full_name == "acme/web"
    assert ev.pr.head_sha == "2" * 40 and ev.pr.labels == ["backend"]


def test_pull_request_synchronize_carries_before() -> None:
    ev = parse_event("pull_request", load_fixture("github", "pull_request.synchronize"), "d-2")
    assert isinstance(ev, PrEvent)
    assert ev.kind == "pr_synchronized" and ev.before_sha == "2" * 40 and ev.pr.head_sha == "3" * 40


def test_pull_request_closed_merged_state() -> None:
    ev = parse_event("pull_request", load_fixture("github", "pull_request.closed"), "d-3")
    assert isinstance(ev, PrEvent) and ev.kind == "pr_closed" and ev.pr.state == "merged"


def test_installation_created() -> None:
    ev = parse_event("installation", load_fixture("github", "installation.created"), "d-4")
    assert isinstance(ev, InstallationChanged)
    assert ev.action == "created" and ev.installation_id == 42
    assert ev.account.id == "9001" and ev.account.type == "Organization"
    assert [r.full_name for r in ev.repositories_added] == ["acme/web"]


def test_installation_repositories_added() -> None:
    ev = parse_event(
        "installation_repositories",
        load_fixture("github", "installation_repositories.added"),
        "d-5",
    )
    assert isinstance(ev, InstallationChanged) and ev.action == "repos_added"
    assert ev.repositories_added[0].provider_repo_id == "1002"


def test_issue_comment_on_pr() -> None:
    ev = parse_event("issue_comment", load_fixture("github", "issue_comment.created"), "d-6")
    assert isinstance(ev, CommentCreated)
    assert ev.pr_number == 7 and ev.body == "@hootpr review" and ev.thread_ref is None


def test_unknown_events_are_ignored() -> None:
    assert parse_event("ping", load_fixture("github", "ping"), "d-7") is None
    payload = load_fixture("github", "pull_request.opened") | {"action": "labeled"}
    assert parse_event("pull_request", payload, "d-8") is None


def test_events_round_trip_through_json() -> None:
    ev = parse_event("pull_request", load_fixture("github", "pull_request.opened"), "d-1")
    assert ev is not None
    again = event_adapter.validate_python(event_adapter.dump_python(ev, mode="json"))
    assert again == ev


def test_review_comment_carries_location_and_thread() -> None:
    ev = parse_event(
        "pull_request_review_comment",
        load_fixture("github", "pull_request_review_comment.created"),
        "d1",
    )
    assert isinstance(ev, CommentCreated)
    assert (ev.is_review_comment, ev.thread_ref, ev.path, ev.line) == (
        True,
        "501",
        "src/login.py",
        2,
    )
    assert ev.diff_hunk and ev.url.endswith("#discussion_r9001")


def test_issue_comment_is_top_level() -> None:
    ev = parse_event("issue_comment", load_fixture("github", "issue_comment.created"), "d2")
    assert isinstance(ev, CommentCreated) and not ev.is_review_comment and ev.thread_ref is None
    assert ev.url.endswith("#issuecomment-555")
    assert ev.author_association == "MEMBER"


def test_review_comment_carries_author_association() -> None:
    ev = parse_event(
        "pull_request_review_comment",
        load_fixture("github", "pull_request_review_comment.created"),
        "d1",
    )
    assert isinstance(ev, CommentCreated) and ev.author_association == "CONTRIBUTOR"


@pytest.mark.parametrize(("action", "resolved"), [("resolved", True), ("unresolved", False)])
def test_review_thread_events(action: str, resolved: bool) -> None:
    payload = load_fixture("github", "pull_request_review_thread.resolved")
    payload["action"] = action
    ev = parse_event("pull_request_review_thread", payload, "d3")
    assert isinstance(ev, ThreadStatusChanged)
    assert (ev.pr_number, ev.thread_ref, ev.resolved, ev.installation_id) == (
        7,
        "501",
        resolved,
        42,
    )
    assert event_adapter.validate_python(ev.model_dump()) == ev


def test_review_thread_without_comments_is_ignored() -> None:
    payload = load_fixture("github", "pull_request_review_thread.resolved")
    payload["thread"]["comments"] = []
    assert parse_event("pull_request_review_thread", payload, "d4") is None
