"""Inline review comment body, CodeRabbit layout (spec §7.7, plan Q6)."""

from app.review.findings import Candidate

SEVERITY_LABEL = {
    "critical": "🔴 Critical",
    "major": "🟠 Major",
    "minor": "🟡 Minor",
    "nitpick": "🔵 Trivial",
}
AGENT_PROMPT_BODY_MAX = 600


def kind_label(c: Candidate) -> str:
    if c.severity == "nitpick" or c.category in ("style", "docs", "test"):
        return "🧹 Nitpick"
    if c.category in ("bug", "security"):
        return "⚠️ Potential issue"
    return "🛠️ Refactor suggestion"


def agent_prompt(c: Candidate) -> str:
    """The collapsed "Prompt for AI Agents" text (plain prose, never a code fence)."""
    body = " ".join(c.body.split())[:AGENT_PROMPT_BODY_MAX].replace("```", "'''")
    title = c.title.rstrip(".").replace("```", "'''")
    where = (
        f"around lines {c.start} - {c.end_line}"
        if c.start_line is not None and c.start_line != c.end_line
        else f"at line {c.end_line}"
    )
    also = (
        " The same issue also appears at lines "
        + ", ".join(f"{a}-{b}" for a, b in c.also_applies)
        + "."
        if c.also_applies
        else ""
    )
    return (
        f"In `{c.path}` {where}, {title}. {body}{also} "
        "Verify this finding against the current code and only fix it if needed."
    )


def render_inline(c: Candidate) -> str:
    header = f"_{kind_label(c)}_ | _{SEVERITY_LABEL[c.severity]}_"
    lines = [header, "", f"**{c.title}**", "", c.body]
    if c.also_applies:
        lines += ["", "Also applies to: " + ", ".join(f"{a}-{b}" for a, b in c.also_applies)]
    if c.anchor_note:
        lines += ["", f"_Note: {c.anchor_note}._"]
    lines += [
        "",
        "<details>",
        "<summary>🤖 Prompt for AI Agents</summary>",
        "",
        "```",
        agent_prompt(c),
        "```",
        "",
        "</details>",
    ]
    return "\n".join(lines)


def render_review_body(actionable: int, additional: int) -> str:
    text = f"**Actionable comments posted: {actionable}**"
    if additional:
        noun = "comment is" if additional == 1 else "comments are"
        text += f"\n\n{additional} additional {noun} in the walkthrough comment."
    return text
