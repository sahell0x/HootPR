"""Comment bodies of finishing touches (CodeRabbit-style). All model text is hardened by the
caller before it reaches these functions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.billing.pricing import fmt_credits
from app.chat.replies import humanize_seconds, render_actions
from app.finishing.commands import LABELS, Delivery, Kind

EMOJI: dict[Kind, str] = {
    "docstrings": "📝",
    "unit_tests": "🧪",
    "autofix": "🔧",
    "simplify": "♻️",
    "fix_ci": "💚",
    "ci_analysis": "🚨",
    "merge_conflict": "🔀",
    "custom": "✨",
}
MAX_FILES_LISTED = 25


def ci_marker(sha: str) -> str:
    return f"<!-- hootpr:ci-analysis:{sha[:40]} -->"


def label(kind: Kind, recipe: str | None = None) -> str:
    return f"Recipe `{recipe}`" if kind == "custom" and recipe else LABELS[kind]


def delivery_phrase(delivery: Delivery, head_ref: str) -> str:
    if delivery == "commit":
        return f"commit the changes to `{head_ref}`"
    if delivery == "stacked_pr":
        return f"open a stacked pull request against `{head_ref}`"
    return "post the result here"


def render_queued(
    author: str, kind: Kind, recipe: str | None, delivery: Delivery, head_ref: str
) -> str:
    return render_actions(
        author,
        [f"{EMOJI[kind]} {label(kind, recipe)} started."],
        f"HootPR will {delivery_phrase(delivery, head_ref)} when it is done "
        "(this can take several minutes).",
    )


def render_disabled(author: str, phrase: str, key: str) -> str:
    return f"@{author} `{phrase}` is disabled for this repository (`{key}: false`)."


def render_unknown_recipe(author: str, name: str, names: Sequence[str]) -> str:
    known = ", ".join(f"`{n}`" for n in names) if names else "none"
    return (
        f"@{author} There is no custom recipe named `{name}`. Configured recipes "
        f"(`reviews.finishing_touches.custom` in `.hootpr.yaml`): {known}."
    )


def render_rate_limited(author: str, limit: int, retry_after_s: int) -> str:
    return (
        f"@{author} Rate limited — finishing touches share the review limit of {limit} per hour "
        f"per organization. Try again {humanize_seconds(retry_after_s)}. No credit was charged."
    )


def render_out_of_credits(author: str, balance: Decimal, minimum: Decimal, billing_url: str) -> str:
    return "\n".join(
        [
            f"@{author} **Out of credits.** This organization has {fmt_credits(balance)} credits "
            f"left and a finishing touch needs at least {fmt_credits(minimum)} to start "
            "(finishing touches are metered by AI usage).",
            f"An admin can top up at {billing_url}.",
        ]
    )


@dataclass(frozen=True)
class ResultView:
    author: str
    kind: Kind
    recipe: str | None
    delivery: Delivery
    head_ref: str
    summary: str
    files: Sequence[str]
    verification: str  # verified | failed | couldnt_verify | not_run
    verification_detail: str
    test_command: str | None
    sha: str | None = None
    commit_url: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    downgraded: bool = False
    notes: Sequence[str] = ()


def _verification_line(v: ResultView) -> str:
    cmd = f" (`{v.test_command}`)" if v.test_command else ""
    if v.verification == "verified":
        return f"✅ Tests passed{cmd}."
    if v.verification == "failed":
        return f"❌ Tests are still failing after HootPR's attempts{cmd}."
    if v.verification == "couldnt_verify":
        return f"⚠️ Couldn't verify: {v.verification_detail or 'the tests could not be run'}."
    return "Not verified (documentation-only change)." if v.kind == "docstrings" else "Not run."


def render_result(v: ResultView) -> str:
    title = f"{EMOJI[v.kind]} {label(v.kind, v.recipe)}"
    if v.delivery == "commit" and v.sha:
        where = f"Committed [`{v.sha[:7]}`]({v.commit_url})" if v.commit_url else "Committed"
        delivered = f"{where} to `{v.head_ref}`."
    elif v.pr_number is not None:
        link = f"[#{v.pr_number}]({v.pr_url})" if v.pr_url else f"#{v.pr_number}"
        delivered = f"Opened stacked pull request {link} against `{v.head_ref}`."
    else:
        delivered = "Delivered."
    lines = [f"@{v.author} **{title}** is done.", "", f"- {delivered}"]
    if v.downgraded:
        lines.append(
            "- The tests did not pass, so the change was delivered as a stacked pull request "
            "instead of a commit on your branch."
        )
    lines.append(f"- Verification: {_verification_line(v)}")
    lines += [f"- {n}" for n in v.notes]
    if v.files:
        shown = list(v.files)[:MAX_FILES_LISTED]
        more = len(v.files) - len(shown)
        lines += [
            "",
            "<details>",
            f"<summary>Files changed ({len(v.files)})</summary>",
            "",
            *[f"- `{p}`" for p in shown],
            *([f"- … and {more} more"] if more > 0 else []),
            "",
            "</details>",
        ]
    if v.summary.strip():
        lines += ["", "**Summary**", "", v.summary.strip()]
    if v.verification in ("failed", "couldnt_verify") and v.verification_detail:
        detail = v.verification_detail.replace("```", "`​``")[-3000:]
        lines += [
            "",
            "<details>",
            "<summary>Test output</summary>",
            "",
            "```text",
            detail,
            "```",
            "",
            "</details>",
        ]
    return "\n".join(lines)


def render_no_changes(author: str, kind: Kind, recipe: str | None, reason: str) -> str:
    return (
        f"@{author} {EMOJI[kind]} {label(kind, recipe)}: no changes were made — {reason} "
        "No credit was charged."
    )


def render_failed(author: str, kind: Kind, recipe: str | None, reason: str) -> str:
    return (
        f"@{author} {EMOJI[kind]} {label(kind, recipe)} could not be completed: {reason} "
        "No credit was charged."
    )


@dataclass(frozen=True)
class CiItem:
    job: str
    title: str
    root_cause: str
    fix: str
    path: str | None
    line: int | None
    caused_by_pr: bool


def render_ci_analysis(
    sha: str, items: Sequence[CiItem], job_urls: dict[str, str], mention: str
) -> str:
    lines = [
        ci_marker(sha),
        "## 🚨 CI failure analysis",
        "",
        f"HootPR analysed the failed CI jobs of commit `{sha[:7]}`.",
        "",
    ]
    if not items:
        lines.append("No failed jobs with usable logs were found.")
    for it in items:
        where = f" · `{it.path}:{it.line}`" if it.path and it.line else ""
        url = job_urls.get(it.job)
        job = f"[{it.job}]({url})" if url else it.job
        tag = "" if it.caused_by_pr else " _(likely unrelated to this pull request)_"
        lines += [
            f"### ❌ {job} — {it.title}{tag}",
            "",
            f"**Root cause:** {it.root_cause}{where}",
            "",
            f"**Fix:** {it.fix}",
            "",
        ]
    lines += ["---", f"Comment `{mention} fix ci` to let HootPR push a fix."]
    return "\n".join(lines)
