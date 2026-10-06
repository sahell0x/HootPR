"""Linked-issue fetching and assessment (spec §10.2, CodeRabbit "Assessment against linked
issues")."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.logging import get_logger
from app.merge.context import render_pr_context
from app.merge.issue_refs import IssueRef
from app.merge.prompts import LINKED_ISSUES_SYSTEM
from app.merge.schemas import Assessment, LinkedIssuesAssessment
from app.platforms.base import FileDiff, GitPlatform, NotFoundError, RepoRef
from app.platforms.issues import Issue
from app.review.llm import LLMLike
from app.review.prompts import system_prompt
from app.review.safety import clean_prose, untrusted
from app.review.schemas import WalkthroughSummary

log = get_logger(__name__)
ISSUE_BODY_CHARS = 3000
MAX_OBJECTIVES = 5
ICON: dict[str, str] = {
    "addressed": "✅",
    "partially": "⚠️",
    "not_addressed": "❌",
    "unclear": "❓",
    "unavailable": "❓",
}


@dataclass(frozen=True)
class Objective:
    text: str
    status: Assessment
    explanation: str


@dataclass
class LinkedIssue:
    ref: IssueRef
    label: str  # "#12" or "owner/repo#12"
    repo: str  # full name of the issue's repository
    issue: Issue | None  # None: could not be fetched (or not allowed)
    overall: str = "unavailable"  # Assessment | "unavailable"
    objectives: list[Objective] = field(default_factory=list)
    note: str = ""


def fetch_linked_issues(
    platform: GitPlatform,
    own: RepoRef,
    refs: Sequence[IssueRef],
    allow_foreign: Callable[[str], bool],
) -> list[LinkedIssue]:
    """Fetch each referenced issue. Foreign repositories are only read when ``allow_foreign``
    says so (same org, and never private data into a public repository)."""
    out: list[LinkedIssue] = []
    for r in refs:
        repo = r.repo or own.full_name
        item = LinkedIssue(r, r.label(own.full_name), repo, None)
        out.append(item)
        if r.repo is not None and not allow_foreign(r.repo):
            item.note = "not a repository HootPR can read for this pull request"
            continue
        target = own if r.repo is None else RepoRef(own.provider, r.repo, r.repo)
        try:
            item.issue = platform.get_issue(target, r.number)
        except NotFoundError:
            item.note = "issue not found"
        except Exception:
            log.warning("linked_issue_fetch_failed", issue=item.label, exc_info=True)
            item.note = "could not be fetched"
    return out


def assess_linked_issues(
    llm: LLMLike,
    issues: list[LinkedIssue],
    title: str,
    body: str,
    summary: WalkthroughSummary | None,
    files: Sequence[FileDiff],
    cfg: HootPRConfig,
    *,
    trace: TraceContext,
    host: str | None,
) -> None:
    """Fill ``overall``/``objectives`` in place (review role, one call for all issues)."""
    todo = [i for i in issues if i.issue is not None]
    if not todo:
        return
    blocks = [
        f"### ISSUE {i.label}\n"
        + untrusted(
            f"issue:{i.label}",
            f"title: {i.issue.title}\n\n{i.issue.body[:ISSUE_BODY_CHARS]}" if i.issue else "",
        )
        for i in todo
    ]
    prompt = "\n\n".join([*blocks, render_pr_context(title, body, summary, files)])
    try:
        res = llm.complete(
            "review",
            [
                {"role": "system", "content": system_prompt(LINKED_ISSUES_SYSTEM, cfg)},
                {"role": "user", "content": prompt},
            ],
            response_model=LinkedIssuesAssessment,
            max_output_tokens=2500,
            trace=trace,
        )
    except StructuredOutputError:
        for i in todo:
            i.overall, i.note = "unclear", "assessment unavailable"
        return
    parsed = cast(LinkedIssuesAssessment, res.parsed)
    by_label = {a.issue.strip().lower(): a for a in parsed.issues}
    for i in todo:
        a = by_label.get(i.label.lower())
        if a is None:
            i.overall, i.note = "unclear", "not assessed"
            continue
        i.overall = a.overall
        i.objectives = [
            Objective(
                clean_prose(" ".join(o.objective.split()), 200, host),
                o.status,
                clean_prose(" ".join(o.explanation.split()), 400, host),
            )
            for o in a.objectives[:MAX_OBJECTIVES]
        ]


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_linked_issues(issues: Sequence[LinkedIssue]) -> str:
    """``## Assessment against linked issues`` (CodeRabbit layout)."""
    if not issues:
        return ""
    rows = ["## Assessment against linked issues", "", "| Objective | Addressed | Explanation |"]
    rows.append("|---|---|---|")
    for i in issues:
        title = _cell(i.issue.title[:120]) if i.issue else ""
        head = f"{i.label}" + (f" {title}" if title else "")
        if i.issue is None or not i.objectives:
            why = i.note or ("not assessed" if i.issue else "unavailable")
            rows.append(f"| {head} | {ICON.get(i.overall, '❓')} | {_cell(why)} |")
            continue
        for o in i.objectives:
            obj = f"{_cell(o.text)} ({i.label})"
            rows.append(f"| {obj} | {ICON[o.status]} | {_cell(o.explanation)} |")
    return "\n".join([*rows, ""])
