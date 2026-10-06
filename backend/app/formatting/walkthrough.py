"""Walkthrough comment rendering (CodeRabbit layout, spec §7.7)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.billing.pricing import ceil_whole, distribute_whole, fmt_credits, stage_label, whole
from app.config.schema import Reviews
from app.review.findings import Candidate
from app.review.safety import harden_text
from app.review.stages.diff_filter import SkippedFile
from app.review.tool_results import ToolRunRecord

WALKTHROUGH_MARKER = "<!-- hootpr:walkthrough -->"
TIP = "Tip: comment `@hootpr help` to see what HootPR can do."
SUMMARY_MARKER = "hootpr:summary"
EFFORT_LABEL = {1: "Trivial", 2: "Simple", 3: "Moderate", 4: "Complex", 5: "Critical"}
MAX_LISTED_SKIPPED = 50
MERMAID_MAX_CHARS = 6000


def _path_cell(path: str) -> str:
    return "`" + path.replace("`", "'").replace("|", "\\|") + "`"


@dataclass(frozen=True)
class ChangeRow:
    files: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class NoteComment:
    """A finding shown inside the walkthrough instead of inline."""

    path: str
    start_line: int | None
    end_line: int
    severity: str
    title: str
    body: str

    @classmethod
    def from_candidate(cls, c: Candidate) -> NoteComment:
        return cls(c.path, c.start_line, c.end_line, c.severity, c.title, c.body)


@dataclass(frozen=True)
class ReviewDetails:
    head_sha: str
    base_sha: str | None
    incremental: bool
    config_source: str
    tools: tuple[ToolRunRecord, ...]
    skipped_files: tuple[SkippedFile, ...]
    # Internal (models / tokens / LLM cost): recorded, never rendered in PR comments.
    models: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    credits_charged: Decimal
    files_reviewed: int
    degraded: dict[str, Any]
    learnings_used: tuple[str, ...] = ()  # hardened, ≤ 100 chars each
    guidelines: tuple[str, ...] = ()  # guideline file paths applied
    # Token metering (credits only, never tokens/$/models): the hold, metered credits per stage
    # (pipeline order, ``STAGE_LABELS`` keys) and whether the credit budget trimmed the review.
    credits_reserved: Decimal | None = None
    credits_by_stage: tuple[tuple[str, Decimal], ...] = ()
    budget_reached: bool = False


@dataclass(frozen=True)
class WalkthroughData:
    walkthrough: str
    changes: tuple[ChangeRow, ...]
    sequence_diagrams: tuple[str, ...]
    effort: int
    effort_minutes: int
    poem: str | None
    actionable: int
    additional: tuple[NoteComment, ...]
    unposted: tuple[NoteComment, ...]
    warnings: tuple[str, ...]
    details: ReviewDetails
    # Extra rendered sections (phase 5: linked issues, related PRs, pre-merge checks, slop note),
    # placed after the effort estimate. Each is trusted, already-hardened markdown.
    extra_sections: tuple[str, ...] = ()


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _mermaid_ok(d: str) -> bool:
    s = d.strip()
    return s.startswith("sequenceDiagram") and "```" not in s and len(s) <= MERMAID_MAX_CHARS


def _span(n: NoteComment) -> str:
    if n.start_line and n.start_line < n.end_line:
        return f"{n.start_line}-{n.end_line}"
    return str(n.end_line)


def _notes(summary: str, notes: tuple[NoteComment, ...]) -> list[str]:
    out = ["<details>", f"<summary>{summary} ({len(notes)})</summary>", ""]
    for n in notes:
        head = f"**`{_cell(n.path)}` ({_span(n)})** — _{n.severity}_ — **{n.title}**"
        out += [head, "", n.body, ""]
    return [*out, "</details>", ""]


def _skipped_lines(skipped: tuple[SkippedFile, ...] | list[SkippedFile], indent: str) -> list[str]:
    return [
        f"{indent}- `{_cell(s.path)}` — {s.reason.replace('_', ' ')}"
        for s in skipped[:MAX_LISTED_SKIPPED]
    ]


def _details(d: ReviewDetails) -> list[str]:
    kind = "Incremental" if d.incremental else "Full review"
    base = (d.base_sha or "")[:7]
    out = [
        "<details>",
        "<summary>📜 Review details</summary>",
        "",
        f"- **Configuration used:** {d.config_source}",
        f"- **Review type:** {kind} (`{base}` → `{d.head_sha[:7]}`)",
        f"- **Files reviewed:** {d.files_reviewed}",
    ]
    if d.skipped_files:
        out.append(f"- **Files skipped ({len(d.skipped_files)}):**")
        out += _skipped_lines(d.skipped_files, "  ")
    if d.learnings_used:
        out.append(f"- **🧠 Learnings used:** {len(d.learnings_used)}")
        out += [f"  - {' '.join(text.split())}" for text in d.learnings_used]
    if d.guidelines:
        out.append("- **Code guidelines:** " + ", ".join(_cell(p) for p in d.guidelines))
    if d.tools:
        out.append(
            "- **Tools:** "
            + ", ".join(
                f"{t.tool}: {t.status}"
                + (f" ({t.findings_count} findings)" if t.status == "ok" else "")
                for t in d.tools
            )
        )
    out.append(_credits_line(d))
    if d.budget_reached:
        out.append(
            "- **Note:** this review was trimmed to fit the credits reserved for it; "
            "some review tasks were skipped."
        )
    if d.degraded:
        out.append("- **Degraded:** " + "; ".join(f"{k}: {v}" for k, v in d.degraded.items()))
    return [*out, "", "</details>", ""]


def _credits_line(d: ReviewDetails) -> str:
    """``Credits: 285 (Walkthrough 40 · Review agents 210 · …) · 315 of 600 reserved
    returned`` — whole credits only; the stage parts add up to the charge."""
    charged = whole(d.credits_charged)
    if d.credits_reserved is None:
        return f"- **Credits charged:** {fmt_credits(charged)}"
    shown = distribute_whole([Decimal(v) for _, v in d.credits_by_stage], charged)
    parts = [
        f"{stage_label(k)} {fmt_credits(n)}"
        for (k, _), n in zip(d.credits_by_stage, shown, strict=True)
        if n > 0
    ]
    line = f"- **Credits:** {fmt_credits(charged)}" + (f" ({' · '.join(parts)})" if parts else "")
    reserved = ceil_whole(d.credits_reserved)
    returned = reserved - charged
    if returned > 0:
        line += f" · {fmt_credits(returned)} of {fmt_credits(reserved)} reserved returned"
    return line


WARNING_MAX = 500


def harden_warning(text: str) -> str:
    """Warnings can quote repo-controlled text (YAML keys): one line, no pings/HTML/quick
    actions."""
    return harden_text(" ".join(text.split()), WARNING_MAX)


def render_walkthrough(d: WalkthroughData, reviews: Reviews) -> str:
    """The single walkthrough comment (CodeRabbit section order, toggled by ``reviews.*``)."""
    body: list[str] = []
    if d.warnings:
        body += ["> [!WARNING]", *(f"> {harden_warning(w)}" for w in d.warnings), ""]
    body += ["## Walkthrough", "", d.walkthrough.strip() or "_No summary available._", ""]
    if reviews.changed_files_summary and d.changes:
        body += ["## Changes", "", "| Cohort / File(s) | Summary |", "|---|---|"]
        body += [
            f"| {', '.join('`' + _cell(p) + '`' for p in r.files)} | {_cell(r.summary)} |"
            for r in d.changes
        ]
        body.append("")
    diagrams = [x.strip() for x in d.sequence_diagrams if _mermaid_ok(x)]
    if not reviews.sequence_diagrams:
        diagrams = []
    if diagrams:
        body += ["## Sequence Diagram(s)", ""]
        for x in diagrams:
            body += ["```mermaid", x, "```", ""]
    if reviews.estimate_code_review_effort:
        e = min(5, max(1, d.effort))
        body += [
            "## Estimated code review effort",
            "",
            f"🎯 {e} ({EFFORT_LABEL[e]}) | ⏱️ ~{max(1, d.effort_minutes)} minutes",
            "",
        ]
    for section in d.extra_sections:
        if section.strip():
            body += [section.rstrip(), ""]
    if reviews.poem and d.poem:
        body += ["## Poem", "", *(f"> {line}" for line in d.poem.strip().splitlines()), ""]
    if reviews.collapse_walkthrough:
        body = ["<details>", "<summary>📝 Walkthrough</summary>", "", *body, "</details>", ""]
    tail: list[str] = []
    if d.unposted:
        tail += _notes("⚠️ Comments that could not be posted inline", d.unposted)
    if d.additional:
        tail += _notes("🧹 Additional comments", d.additional)
    tail += _details(d.details)
    return "\n".join([WALKTHROUGH_MARKER, *body, *tail, "---", TIP])


def render_summary_block(summary: str) -> str:
    """The "Summary by HootPR" block placed in the PR description (``high_level_summary``)."""
    return "## Summary by HootPR\n\n" + summary.strip()


def render_no_files_notice(skipped: list[SkippedFile], head_sha: str) -> str:
    lines = [
        WALKTHROUGH_MARKER,
        "## Review skipped",
        "",
        f"No reviewable files in `{head_sha[:7]}`: every changed file was excluded.",
        "",
        *_skipped_lines(skipped, ""),
    ]
    return "\n".join([*lines, "", "---", TIP])
