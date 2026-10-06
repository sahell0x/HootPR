from decimal import Decimal
from typing import Any

import pytest

from app.config.schema import HootPRConfig
from app.llm.types import Usage
from app.platforms.base import PlatformError, PullRequest, RepoRef
from app.platforms.diff import build_file_diff
from app.platforms.local import LocalPlatform
from app.review.anchoring import DiffIndex
from app.review.engine import EngineInputs, EngineResult
from app.review.findings import Candidate
from app.review.posting import PostOutcome, make_details, post_results
from app.review.stages.summarize import fallback_summary

REF = RepoRef("github", "1", "acme/web")
# new side: 1 x, 2 y (added), 3 z (added), 4 w
F = build_file_diff("a.py", "@@ -1,2 +1,3 @@\n x\n+y\n+z\n w\n", "modified")
PR = PullRequest(7, "t", "body", "alice", "open", False, "main", "f", "1" * 40, "2" * 40, (), "")


def c(
    title: str, end: int, severity: str = "major", placement: str = "inline", **kw: Any
) -> Candidate:
    base: dict[str, Any] = dict(
        path="a.py", start_line=None, end_line=end, severity=severity, category="bug",
        title=title, body="b", confidence=0.9, verdict="keep", placement=placement,
    )  # fmt: skip
    base.update(kw)
    return Candidate(**base)


def result(inline: list[Candidate], additional: list[Candidate] | None = None) -> EngineResult:
    additional = additional or []
    return EngineResult(
        "reviewed", [F], ["a.py"], [], [], [*inline, *additional], inline, additional,
        fallback_summary([F], None), [], {}, Usage(10, 0, 5), Decimal("0.001"),
        ["model-review"], False, None,
    )  # fmt: skip


def platform(provider: str = "github") -> LocalPlatform:
    lp = LocalPlatform(provider=provider)  # type: ignore[arg-type]
    lp.add_pull_request(REF, PR, [F])
    return lp


def post(lp: LocalPlatform, res: EngineResult, cfg: HootPRConfig | None = None) -> PostOutcome:
    cfg = cfg or HootPRConfig()
    inputs = EngineInputs("r", None, REF, PR, "1" * 40, "2" * 40, False, cfg)  # type: ignore[arg-type]
    return post_results(
        lp, REF, 7, "2" * 40, res, cfg, make_details(res, inputs, Decimal("1")), [],
        diff=DiffIndex([F]),
    )  # fmt: skip


def test_posts_one_review_walkthrough_and_summary_block() -> None:
    lp = platform()
    a, b = c("A", 2), c("B", 3)
    out = post(lp, result([a, b], [c("N", 3, "nitpick", "additional")]))
    assert out.posted == 2 and out.unposted == []
    review = lp.reviews[0]
    assert review.event == "COMMENT"
    assert review.summary is not None
    assert review.summary.startswith("**Actionable comments posted: 2**")
    assert [x.end_line for x in review.comments] == [2, 3]
    assert a.posted and a.provider_comment_id
    walkthrough = lp.comments[("1", 7)][0].body
    assert walkthrough.startswith("<!-- hootpr:walkthrough -->")
    assert "Additional comments (1)" in walkthrough
    assert out.walkthrough_id == lp.comments[("1", 7)][0].id
    assert "## Summary by HootPR" in lp.descriptions[("1", 7)]
    assert lp.descriptions[("1", 7)].startswith("body")  # the author's text is kept


def test_high_level_summary_off_leaves_the_description_alone() -> None:
    lp = platform()
    post(lp, result([]), HootPRConfig.model_validate({"reviews": {"high_level_summary": False}}))
    assert lp.descriptions[("1", 7)] == "body"


def test_request_changes_only_with_workflow_and_blocking_findings() -> None:
    lp = platform()
    cfg = HootPRConfig.model_validate({"reviews": {"request_changes_workflow": True}})
    post(lp, result([c("A", 2, "critical")]), cfg)
    post(lp, result([c("B", 2, "minor")]), cfg)
    post(lp, result([c("C", 2, "critical")]))  # workflow off
    assert [r.event for r in lp.reviews] == ["REQUEST_CHANGES", "COMMENT", "COMMENT"]


def test_post_review_422_moves_comments_into_walkthrough() -> None:
    lp = platform()
    lp.invalid_anchors = {("a.py", 2)}
    moved = c("Moved", 2)
    out = post(lp, result([moved]))
    assert out.posted == 0 and out.unposted == [moved] and moved.placement == "unposted"
    assert lp.reviews == []
    assert "Comments that could not be posted inline (1)" in lp.comments[("1", 7)][0].body


def test_422_then_reanchor_to_changed_line_succeeds() -> None:
    lp = platform()
    lp.invalid_anchors = {("a.py", 4)}  # context line: GitHub rejected it
    ctx_line = c("Ctx", 4, suggestion="w2")
    out = post(lp, result([ctx_line]))
    assert out.posted == 1 and ctx_line.end_line == 3 and ctx_line.suggestion is None
    assert ctx_line.anchor_note == "re-anchored from line 4"


def test_gitlab_partial_failure_goes_to_walkthrough() -> None:
    lp = platform("gitlab")
    lp.invalid_anchors = {("a.py", 3)}
    ok, bad = c("Ok", 2), c("Bad", 3)
    out = post(lp, result([ok, bad]))
    assert out.posted == 1 and out.unposted == [bad] and ok.posted and not bad.posted
    assert "Comments that could not be posted inline (1)" in lp.comments[("1", 7)][0].body


def test_no_inline_comments_posts_only_the_walkthrough() -> None:
    lp = platform()
    out = post(lp, result([]))
    assert lp.reviews == [] and out.walkthrough_id and out.posted == 0


def test_non_422_platform_errors_propagate() -> None:
    lp = platform()
    lp.fail_next = PlatformError(502, "bad gateway")
    with pytest.raises(PlatformError):
        post(lp, result([c("A", 2)]))


def test_context_line_comment_carries_old_line_and_old_path() -> None:
    lp = platform("gitlab")
    out = post(lp, result([c("ctx", 4)]))  # line 4 "w" is a context line (old line 2)
    assert out.posted == 1
    sent = lp.reviews[0].comments[0]
    assert sent.old_line == 2 and sent.old_path == "a.py"
    lp2 = platform("gitlab")
    post(lp2, result([c("added", 2)]))
    assert lp2.reviews[0].comments[0].old_line is None


def test_details_carry_hardened_learnings_and_guidelines() -> None:
    from app.knowledge.base import LearningHit

    res = result([])
    res.learnings_used = [
        LearningHit("1", "Ping @alice <b>about</b>\n\nprint " + "x" * 200, "repo", None, 0.9)
    ]
    res.guidelines_used = ["CLAUDE.md"]
    inputs = EngineInputs("r", None, REF, PR, "1" * 40, "2" * 40, False, HootPRConfig())  # type: ignore[arg-type]
    d = make_details(res, inputs, Decimal("1"))
    [text] = d.learnings_used
    assert "@alice" not in text and "<b>" not in text and "\n" not in text and len(text) <= 100
    assert d.guidelines == ("CLAUDE.md",)


def _titled(title: str, body: str) -> tuple[LocalPlatform, EngineResult]:
    lp = LocalPlatform()
    lp.add_pull_request(
        REF,
        PullRequest(
            7, title, body, "alice", "open", False, "main", "f", "1" * 40, "2" * 40, (), ""
        ),
        [F],
    )
    res = result([])
    res.summary = res.summary.model_copy(update={"title": "Generated title"})
    return lp, res


def _post_titled(lp: LocalPlatform, res: EngineResult, title: str) -> None:
    cfg = HootPRConfig()
    inputs = EngineInputs("r", None, REF, PR, "1" * 40, "2" * 40, False, cfg)  # type: ignore[arg-type]
    post_results(
        lp, REF, 7, "2" * 40, res, cfg, make_details(res, inputs, Decimal("1")), [],
        diff=DiffIndex([F]), pr_title=title,
    )  # fmt: skip


def test_title_and_description_placeholders_are_replaced() -> None:
    lp, res = _titled("WIP @hootpr", "Details\n\n@hootpr summary")
    _post_titled(lp, res, "WIP @hootpr")
    assert lp.get_pull_request(REF, 7).title == "Generated title"
    desc = lp.descriptions[("1", 7)]
    assert desc.startswith("Details\n\n") and "## Summary by HootPR" in desc
    assert "@hootpr summary" not in desc


def test_title_is_kept_without_the_placeholder() -> None:
    lp, res = _titled("Fix login", "body")
    _post_titled(lp, res, "Fix login")
    assert lp.get_pull_request(REF, 7).title == "Fix login"


def test_title_update_failure_is_not_fatal() -> None:
    lp, res = _titled("@hootpr", "body")

    def boom(*a: object) -> None:
        raise PlatformError(403, "forbidden")

    lp.update_pr_title = boom  # type: ignore[method-assign]
    _post_titled(lp, res, "@hootpr")
    assert lp.comments[("1", 7)][0].body.startswith("<!-- hootpr:walkthrough -->")
