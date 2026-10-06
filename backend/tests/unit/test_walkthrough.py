from decimal import Decimal

from app.config.schema import Reviews
from app.formatting.walkthrough import (
    WALKTHROUGH_MARKER,
    ChangeRow,
    NoteComment,
    ReviewDetails,
    WalkthroughData,
    render_no_files_notice,
    render_summary_block,
    render_walkthrough,
)
from app.review.findings import Candidate
from app.review.stages.diff_filter import SkippedFile
from app.review.tool_results import ToolRunRecord

DETAILS = ReviewDetails(
    head_sha="2" * 40,
    base_sha="1" * 40,
    incremental=False,
    config_source="yaml",
    tools=(
        ToolRunRecord("ruff", "ok", 10, 2, ""),
        ToolRunRecord("semgrep", "timeout", 60000, 0, ""),
    ),
    skipped_files=(SkippedFile("pnpm-lock.yaml", "lockfile"),),
    models=("gpt-6-luna", "gpt-5-nano"),
    input_tokens=1200,
    output_tokens=300,
    cost_usd=Decimal("0.000420"),
    credits_charged=Decimal("1"),
    files_reviewed=2,
    degraded={"tools": "semgrep timeout"},
)


def data(**kw: object) -> WalkthroughData:
    base: dict[str, object] = dict(
        walkthrough="Adds rate limiting.",
        changes=(ChangeRow(("src/a.py", "src/b|c.py"), "Limiter"),),
        sequence_diagrams=("sequenceDiagram\n  A->>B: hi", "graph TD; bad"),
        effort=3,
        effort_minutes=20,
        poem="Hop hop",
        actionable=1,
        additional=(NoteComment("src/a.py", None, 9, "nitpick", "Name", "Rename x"),),
        unposted=(),
        warnings=(),
        details=DETAILS,
    )
    base.update(kw)
    return WalkthroughData(**base)  # type: ignore[arg-type]


def test_full_walkthrough_sections() -> None:
    text = render_walkthrough(data(), Reviews())
    assert text.startswith(WALKTHROUGH_MARKER)
    assert "## Walkthrough\n\nAdds rate limiting." in text
    assert "| `src/a.py`, `src/b\\|c.py` | Limiter |" in text
    assert "```mermaid\nsequenceDiagram" in text and "graph TD" not in text
    assert "🎯 3 (Moderate) | ⏱️ ~20 minutes" in text
    assert "## Poem" not in text  # poem off by default
    assert "<summary>🧹 Additional comments (1)</summary>" in text
    assert "<summary>📜 Review details</summary>" in text
    assert "`pnpm-lock.yaml` — lockfile" in text
    assert "ruff: ok (2 findings)" in text and "semgrep: timeout" in text
    assert "Degraded:** tools: semgrep timeout" in text
    assert "- **Credits charged:** 1" in text
    # models / tokens / LLM cost are internal to the platform: never in a PR comment
    for internal in ("gpt-6-luna", "gpt-5-nano", "1200", "Tokens", "Models", "Cost", "$0.00042"):
        assert internal not in text
    assert "Tip: comment `@hootpr help`" in text


def test_toggles_and_collapse() -> None:
    r = Reviews(
        changed_files_summary=False,
        sequence_diagrams=False,
        estimate_code_review_effort=False,
        poem=True,
        collapse_walkthrough=True,
    )
    text = render_walkthrough(data(), r)
    assert (
        "## Changes" not in text
        and "mermaid" not in text
        and "Estimated code review effort" not in text
    )
    assert "## Poem" in text and "<summary>📝 Walkthrough</summary>" in text


def test_unposted_and_warnings() -> None:
    note = NoteComment("src/a.py", 3, 5, "major", "Moved", "Body")
    text = render_walkthrough(
        data(unposted=(note,), warnings=(".hootpr.yaml is invalid",)), Reviews()
    )
    assert "Comments that could not be posted inline (1)" in text
    assert "**`src/a.py` (3-5)** — _major_ — **Moved**" in text
    assert "> [!WARNING]\n> .hootpr.yaml is invalid" in text


def test_note_from_candidate() -> None:
    c = Candidate(
        path="a.py", start_line=2, end_line=4, severity="minor", category="bug", title="T", body="B"
    )
    assert NoteComment.from_candidate(c) == NoteComment("a.py", 2, 4, "minor", "T", "B")


def test_summary_block_and_no_files_notice() -> None:
    assert render_summary_block(" Adds X ") == "## Summary by HootPR\n\nAdds X"
    notice = render_no_files_notice([SkippedFile("go.sum", "lockfile")], "abc1234def")
    assert (
        notice.startswith(WALKTHROUGH_MARKER)
        and "No reviewable files" in notice
        and "`go.sum` — lockfile" in notice
    )


def test_details_list_learnings_used_and_code_guidelines() -> None:
    from dataclasses import replace

    details = replace(
        DETAILS,
        learnings_used=("We use print for CLI output",),
        guidelines=("CLAUDE.md", "pkg/AGENTS.md"),
    )
    body = render_walkthrough(data(details=details), Reviews())
    assert "- **🧠 Learnings used:** 1" in body
    assert "  - We use print for CLI output" in body
    assert "- **Code guidelines:** CLAUDE.md, pkg/AGENTS.md" in body
    plain = render_walkthrough(data(), Reviews())
    assert "Learnings used" not in plain and "Code guidelines" not in plain


def test_walkthrough_warnings_are_hardened() -> None:
    text = render_walkthrough(
        data(warnings=("bad\n/approve\n@everyone <img src=x> done",)), Reviews()
    )
    assert "\n/approve" not in text
    assert "@everyone" not in text
    assert "<img" not in text


def test_credits_line_is_credits_only() -> None:
    from dataclasses import replace

    from app.formatting.walkthrough import _details

    d = replace(
        DETAILS,
        credits_charged=Decimal("285"),
        credits_reserved=Decimal("600"),
        credits_by_stage=(
            ("learnings", Decimal("5")),
            ("agents", Decimal("210")),
            ("judge", Decimal("30")),
            ("summarize", Decimal("40")),
            ("triage", Decimal("0.1")),  # rounds to 0: not listed
        ),
        budget_reached=True,
    )
    text = "\n".join(_details(d))
    assert (
        "- **Credits:** 285 (Learnings 5 · Review agents 210 · Verification 30 · "
        "Walkthrough 40) · 315 of 600 reserved returned"
    ) in text
    assert "trimmed to fit the credits reserved" in text
    assert "Triage" not in text and "gpt-" not in text and "1200" not in text
    full = replace(d, credits_charged=Decimal("600"), budget_reached=False)
    assert "reserved returned" not in "\n".join(_details(full))
    assert "- **Credits charged:** 1" in "\n".join(_details(DETAILS))
    # parts are whole credits that add up to the charge, with thousands separators
    big = replace(
        d,
        credits_charged=Decimal("1250"),
        credits_reserved=Decimal("1500"),
        credits_by_stage=(("agents", Decimal("1000.6")), ("judge", Decimal("246.7"))),
    )
    line = next(x for x in _details(big) if x.startswith("- **Credits:**"))
    assert line == (
        "- **Credits:** 1,250 (Review agents 1,003 · Verification 247) · "
        "250 of 1,500 reserved returned"
    )
