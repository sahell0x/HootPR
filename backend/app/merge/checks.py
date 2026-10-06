"""Pre-merge checks (spec §10.2, CodeRabbit parity).

Built-in: title, description, docstring coverage, linked-issue assessment; plus custom
natural-language checks. Modes ``off`` (not run) / ``warning`` / ``error``; a failed ``error`` check
that nobody ignored fails the HootPR status. The walkthrough section sits between markers so
``@hootpr ignore pre-merge checks`` can rewrite it in place.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import cast

from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.merge.context import render_pr_context
from app.merge.docstrings import DocstringCoverage
from app.merge.linked_issues import LinkedIssue
from app.merge.prompts import PRE_MERGE_SYSTEM
from app.merge.schemas import CheckStatus, PreMergeVerdicts
from app.platforms.base import FileDiff
from app.review.llm import LLMLike
from app.review.prompts import system_prompt
from app.review.safety import clean_prose, untrusted
from app.review.schemas import WalkthroughSummary

TITLE = "Title check"
DESCRIPTION = "Description check"
DOCSTRINGS = "Docstring Coverage"
ISSUES = "Linked Issues check"
PRE_MERGE_FAILED = "Pre-merge checks failed"
MARKER = "hootpr:pre-merge"
START, END = f"<!-- {MARKER}:start -->", f"<!-- {MARKER}:end -->"
_PLACEHOLDER_TITLE = re.compile(
    r"^(wip|update|updates|fix|fixes|changes?|misc|test|tmp|pr|patch|[\w.-]+/[\w./-]+|[A-Z]+-\d+)$",
    re.I,
)
_MIN_DESCRIPTION_CHARS = 30


@dataclass(frozen=True)
class CheckResult:
    kind: str  # title | description | docstrings | issue_assessment | custom
    name: str
    mode: str  # warning | error
    status: CheckStatus
    explanation: str
    ignored: bool = False
    ignored_by: str | None = None

    @property
    def blocking(self) -> bool:
        return self.mode == "error" and self.status == "failed" and not self.ignored


def any_blocking(results: Sequence[CheckResult]) -> bool:
    return any(r.blocking for r in results)


# --- deterministic fallbacks ---------------------------------------------------------------


def heuristic_title(title: str) -> tuple[CheckStatus, str]:
    t = " ".join(title.split())
    if len(t) < 10 or len(t.split()) < 2 or _PLACEHOLDER_TITLE.match(t):
        return "failed", "The title is too short or generic to describe the change."
    if len(t) > 100:
        return "failed", "The title is longer than 100 characters."
    return "passed", "The title is specific and reasonably short."


def _strip_template(body: str) -> str:
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"(?m)^\s*(#+.*|[-*]\s*\[[ xX]\].*|[-*]\s*)$", "", body)
    return " ".join(body.split())


def heuristic_description(body: str) -> tuple[CheckStatus, str]:
    if len(_strip_template(body)) < _MIN_DESCRIPTION_CHARS:
        return "failed", "The description is empty or only a template; explain what and why."
    return "passed", "The description explains the change."


# --- built-ins -----------------------------------------------------------------------------


def docstring_check(cfg: HootPRConfig, cov: DocstringCoverage | None) -> CheckResult | None:
    c = cfg.reviews.pre_merge_checks.docstrings
    if c.mode == "off":
        return None
    if cov is None:
        return CheckResult(
            "docstrings", DOCSTRINGS, c.mode, "inconclusive", "The code graph was unavailable."
        )
    if cov.total == 0:
        return CheckResult(
            "docstrings", DOCSTRINGS, c.mode, "passed", "No changed functions or classes."
        )
    pct = cov.percent
    if pct >= c.threshold:
        why = f"Docstring coverage is {pct:.2f}% (threshold {c.threshold:.2f}%)."
        return CheckResult("docstrings", DOCSTRINGS, c.mode, "passed", why)
    missing = ", ".join(f"`{m}`" for m in cov.missing[:5])
    why = (
        f"Docstring coverage is {pct:.2f}% which is insufficient. The required threshold is "
        f"{c.threshold:.2f}%." + (f" Missing: {missing}." if missing else "")
    )
    return CheckResult("docstrings", DOCSTRINGS, c.mode, "failed", why)


def issue_check(cfg: HootPRConfig, issues: Sequence[LinkedIssue]) -> CheckResult | None:
    c = cfg.reviews.pre_merge_checks.issue_assessment
    if c.mode == "off":
        return None
    assessed = [i for i in issues if i.issue is not None]
    if not assessed:
        why = "No linked issues were found." if not issues else "Linked issues were unavailable."
        return CheckResult("issue_assessment", ISSUES, c.mode, "inconclusive", why)
    bad = [i.label for i in assessed if i.overall in ("not_addressed", "partially")]
    if bad:
        why = f"Not fully addressed: {', '.join(bad)}."
        return CheckResult("issue_assessment", ISSUES, c.mode, "failed", why)
    if all(i.overall == "addressed" for i in assessed):
        why = "The changes address the linked issues."
        return CheckResult("issue_assessment", ISSUES, c.mode, "passed", why)
    why = "Could not determine whether the linked issues are addressed."
    return CheckResult("issue_assessment", ISSUES, c.mode, "inconclusive", why)


def llm_checks(
    llm: LLMLike,
    cfg: HootPRConfig,
    title: str,
    body: str,
    summary: WalkthroughSummary | None,
    files: Sequence[FileDiff],
    *,
    trace: TraceContext,
    host: str | None,
) -> list[CheckResult]:
    """Title, description and custom checks in one ``review``-role call; a failed call falls
    back to heuristics (title/description) and ``inconclusive`` (custom checks)."""
    pm = cfg.reviews.pre_merge_checks
    wanted: list[tuple[str, str, str, str]] = []  # (kind, name, mode, instructions)
    if pm.title.mode != "off":
        extra = f" Extra requirements: {pm.title.requirements}" if pm.title.requirements else ""
        wanted.append(("title", TITLE, pm.title.mode, f"Title quality.{extra}"))
    if pm.description.mode != "off":
        wanted.append(("description", DESCRIPTION, pm.description.mode, "Description quality."))
    for c in pm.custom_checks:
        if c.mode != "off":
            wanted.append(("custom", c.name, c.mode, c.instructions))
    if not wanted:
        return []
    verdicts: dict[str, tuple[CheckStatus, str]] = {}
    try:
        checks = "\n\n".join(
            f"### CHECK {name}\n" + untrusted(f"check:{name}", instr)
            for _, name, _, instr in wanted
        )
        res = llm.complete(
            "review",
            [
                {"role": "system", "content": system_prompt(PRE_MERGE_SYSTEM, cfg)},
                {
                    "role": "user",
                    "content": checks + "\n\n" + render_pr_context(title, body, summary, files),
                },
            ],
            response_model=PreMergeVerdicts,
            max_output_tokens=1500,
            trace=trace,
        )
        for v in cast(PreMergeVerdicts, res.parsed).checks:
            verdicts[v.name.strip().lower()] = (
                v.status,
                clean_prose(" ".join(v.explanation.split()), 400, host),
            )
    except StructuredOutputError:
        verdicts = {}
    out: list[CheckResult] = []
    for kind, name, mode, _ in wanted:
        got: tuple[CheckStatus, str]
        if name.lower() in verdicts:
            got = verdicts[name.lower()]
        elif kind == "title":
            got = heuristic_title(title)
        elif kind == "description":
            got = heuristic_description(body)
        else:
            got = ("inconclusive", "The check could not be evaluated.")
        out.append(CheckResult(kind, name, mode, got[0], got[1]))
    return out


# --- rendering -----------------------------------------------------------------------------


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _status_cell(r: CheckResult) -> str:
    if r.status == "passed":
        return "✅ Passed"
    if r.status == "inconclusive":
        return "❓ Inconclusive"
    label = "❌ Error" if r.mode == "error" else "⚠️ Warning"
    if r.ignored:
        who = f" by @{r.ignored_by}" if r.ignored_by else ""
        return f"~~{label}~~ Ignored{who}"
    return label


def _table(rows: Sequence[CheckResult]) -> list[str]:
    out = ["| Check name | Status | Explanation |", "|---|---|---|"]
    out += [f"| {_cell(r.name)} | {_status_cell(r)} | {_cell(r.explanation)} |" for r in rows]
    return out


def render_pre_merge(results: Sequence[CheckResult], mention: str = "@hootpr") -> str:
    """The walkthrough section, between ``hootpr:pre-merge`` markers ("" when no checks ran)."""
    if not results:
        return ""
    failed = [r for r in results if r.status == "failed"]
    unclear = [r for r in results if r.status == "inconclusive"]
    passed = [r for r in results if r.status == "passed"]
    body = ["## Pre-merge checks", ""]
    if failed:
        errors = sum(r.mode == "error" for r in failed)
        warnings = len(failed) - errors
        parts = [f"{errors} error" if errors else "", f"{warnings} warning" if warnings else ""]
        counts = ", ".join(x for x in parts if x)
        body += ["<details open>", f"<summary>❌ Failed checks ({counts})</summary>", ""]
        body += [*_table(failed), "", "</details>", ""]
    if unclear:
        body += ["<details>", f"<summary>❓ Inconclusive checks ({len(unclear)})</summary>", ""]
        body += [*_table(unclear), "", "</details>", ""]
    if passed:
        body += ["<details>", f"<summary>✅ Passed checks ({len(passed)} passed)</summary>", ""]
        body += [*_table(passed), "", "</details>", ""]
    if any_blocking(results):
        body += [
            "> [!CAUTION]",
            "> Checks in `error` mode failed, so the HootPR status is failing. Fix them or comment "
            f"`{mention} ignore pre-merge checks` to override.",
            "",
        ]
    return "\n".join([START, *body, END])


def mark_ignored(results: Sequence[CheckResult], by: str) -> list[CheckResult]:
    """Every failed check becomes ignored (``@hootpr ignore pre-merge checks``)."""
    return [
        replace(r, ignored=True, ignored_by=by) if r.status == "failed" and not r.ignored else r
        for r in results
    ]


def replace_section(walkthrough: str, section: str) -> str | None:
    """``walkthrough`` with its pre-merge section swapped for ``section``; ``None`` when the
    walkthrough has no such section."""
    i = walkthrough.find(START)
    j = walkthrough.find(END, i + len(START)) if i != -1 else -1
    if i == -1 or j == -1:
        return None
    return walkthrough[:i] + section + walkthrough[j + len(END) :]
