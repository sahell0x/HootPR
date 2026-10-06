from app.events.models import CommentCreated, PipelineFailed, PrEvent
from app.platforms.gitlab.webhooks import extract_project_id, parse_event, verify_token
from tests.fixtures import load_fixture


def test_verify_token() -> None:
    assert verify_token("abc", "abc")
    assert not verify_token("abc", "abd")
    assert not verify_token("abc", None)
    assert not verify_token("", "")


def test_extract_project_id() -> None:
    assert extract_project_id(load_fixture("gitlab", "merge_request.open")) == "2002"
    assert extract_project_id({}) is None


def test_mr_open() -> None:
    ev = parse_event("Merge Request Hook", load_fixture("gitlab", "merge_request.open"), "u-1")
    assert isinstance(ev, PrEvent) and ev.kind == "pr_opened"
    assert ev.repo.provider == "gitlab" and ev.repo.provider_repo_id == "2002"
    assert ev.repo.private is True
    assert ev.pr.number == 3 and ev.pr.head_sha == "a" * 40 and ev.pr.labels == ["bug"]
    assert ev.pr.base_ref == "main" and ev.pr.head_ref == "fix/pagination"


def test_mr_update_with_new_commits_is_synchronize() -> None:
    ev = parse_event("Merge Request Hook", load_fixture("gitlab", "merge_request.update"), "u-2")
    assert isinstance(ev, PrEvent) and ev.kind == "pr_synchronized"
    assert ev.before_sha == "a" * 40 and ev.pr.head_sha == "b" * 40


def test_mr_update_without_push_is_pr_updated() -> None:
    ev = parse_event(
        "Merge Request Hook", load_fixture("gitlab", "merge_request.update_title"), "g2"
    )
    assert isinstance(ev, PrEvent) and ev.kind == "pr_updated"


def test_diff_note_is_review_comment() -> None:
    ev = parse_event("Note Hook", load_fixture("gitlab", "note.merge_request.diff_note"), "g1")
    assert isinstance(ev, CommentCreated)
    assert (ev.is_review_comment, ev.thread_ref, ev.path, ev.line) == (
        True,
        "disc-701",
        "src/login.py",
        2,
    )
    assert ev.url.endswith("#note_8101")


def test_top_level_note_is_not_a_review_comment() -> None:
    ev = parse_event("Note Hook", load_fixture("gitlab", "note.merge_request"), "g3")
    assert isinstance(ev, CommentCreated) and not ev.is_review_comment
    assert ev.url.endswith("#note_8001") and ev.path is None


def test_mr_draft_to_ready() -> None:
    payload = load_fixture("gitlab", "merge_request.update_title")
    payload["changes"] = {"draft": {"previous": True, "current": False}}
    ev = parse_event("Merge Request Hook", payload, "u-4")
    assert isinstance(ev, PrEvent) and ev.kind == "pr_ready"


def test_mr_merge_is_closed() -> None:
    ev = parse_event("Merge Request Hook", load_fixture("gitlab", "merge_request.merge"), "u-5")
    assert isinstance(ev, PrEvent) and ev.kind == "pr_closed" and ev.pr.state == "merged"


def test_note_on_mr() -> None:
    ev = parse_event("Note Hook", load_fixture("gitlab", "note.merge_request"), "u-6")
    assert isinstance(ev, CommentCreated)
    assert ev.pr_number == 3 and ev.thread_ref == "abc123" and ev.author_username == "dave"


def test_pipeline_failed() -> None:
    ev = parse_event("Pipeline Hook", load_fixture("gitlab", "pipeline.failed"), "u-7")
    assert isinstance(ev, PipelineFailed) and ev.pr_number == 3 and ev.sha == "b" * 40
