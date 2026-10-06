from app.formatting.review_comment import agent_prompt, render_inline, render_review_body
from app.review.findings import Candidate


def test_inline_comment_layout() -> None:
    c = Candidate(
        path="a.py",
        start_line=3,
        end_line=4,
        severity="critical",
        category="security",
        title="SQL injection in get_user",
        body="Use parameters.\n```py\nq(?)\n```",
    )
    text = render_inline(c)
    assert text.splitlines()[0] == "_⚠️ Potential issue_ | _🔴 Critical_"
    assert "**SQL injection in get_user**" in text
    assert "<summary>🤖 Prompt for AI Agents</summary>" in text
    assert "In `a.py` around lines 3 - 4, SQL injection in get_user." in agent_prompt(c)
    assert "```" not in agent_prompt(c)


def test_single_line_prompt_and_anchor_note() -> None:
    c = Candidate(
        path="a.py",
        start_line=None,
        end_line=9,
        severity="major",
        category="security",
        title="Leak.",
        body="b",
        anchor_note="re-anchored from line 12",
    )
    assert "In `a.py` at line 9, Leak." in agent_prompt(c)
    assert "_Note: re-anchored from line 12._" in render_inline(c)


def test_kind_labels() -> None:
    nit = Candidate(
        path="a",
        start_line=None,
        end_line=1,
        severity="nitpick",
        category="bug",
        title="t",
        body="b",
    )
    perf = Candidate(
        path="a",
        start_line=None,
        end_line=1,
        severity="minor",
        category="performance",
        title="t",
        body="b",
    )
    assert render_inline(nit).startswith("_🧹 Nitpick_ | _🔵 Trivial_")
    assert render_inline(perf).startswith("_🛠️ Refactor suggestion_ | _🟡 Minor_")


def test_review_body() -> None:
    assert render_review_body(2, 0) == "**Actionable comments posted: 2**"
    assert "3 additional comments are" in render_review_body(1, 3)
    assert "1 additional comment is" in render_review_body(0, 1)
