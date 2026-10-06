"""Post-merge actions on merged PRs (spec §10.2): configurable recipes under
``reviews.post_merge_actions`` whose results are posted as one comment on the merged PR.

- ``follow_up_issue``: an issue listing HootPR findings that were still open at merge;
- ``changelog``: a drafted changelog entry;
- ``custom``: named natural-language recipes.

Idempotent: a PR that already carries the post-merge comment is skipped (webhook redelivery).
Free of charge; skipped for blocked orgs and orgs without credits.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.loader import load_effective_config
from app.config.schema import HootPRConfig
from app.llm.types import StructuredOutputError, TraceContext
from app.logging import get_logger
from app.merge.context import render_pr_context
from app.merge.prompts import CHANGELOG_ACTION, POST_MERGE_SYSTEM
from app.merge.schemas import MarkdownOutput
from app.models import Finding, PullRequest, Review
from app.platforms.base import FileDiff, GitPlatform, RepoRef
from app.platforms.base import PullRequest as PlatformPR
from app.platforms.factory import close_platform, repo_ref
from app.review.llm import LLMLike, MeteredLLM
from app.review.pipeline import find_reviewable_repo
from app.review.prompts import system_prompt
from app.review.safety import clean_prose, repo_host, untrusted
from app.worker.context import WorkerContext

log = get_logger(__name__)
MARKER = "<!-- hootpr:post-merge -->"
MAX_FOLLOW_UPS = 50
OUTPUT_MAX = 4000


def any_enabled(cfg: HootPRConfig) -> bool:
    a = cfg.reviews.post_merge_actions
    return a.follow_up_issue.enabled or a.changelog.enabled or any(r.enabled for r in a.custom)


def open_findings(s: Session, pr_id: UUID) -> list[Finding]:
    return list(
        s.execute(
            select(Finding)
            .join(Review, Review.id == Finding.review_id)
            .where(Review.pr_id == pr_id, Finding.posted.is_(True), Finding.status == "open")
            .order_by(Finding.created_at)
            .limit(MAX_FOLLOW_UPS)
        ).scalars()
    )


def follow_up_body(pr: PlatformPR, repo_name: str, findings: Sequence[Finding]) -> str:
    lines = [
        f"HootPR comments that were still unresolved when {repo_name}#{pr.number} "
        f"([{pr.title}]({pr.url})) was merged:",
        "",
    ]
    for f in findings:
        span = f"{f.start_line}-{f.end_line}" if f.start_line else str(f.end_line)
        lines.append(f"- [ ] **{f.title}** — `{f.path}:{span}` ({f.severity})")
    return "\n".join(lines)


def run_recipe(
    llm: LLMLike,
    cfg: HootPRConfig,
    action: str,
    pr: PlatformPR,
    files: Sequence[FileDiff],
    *,
    trace: TraceContext,
    host: str | None,
) -> str:
    try:
        res = llm.complete(
            "cheap",
            [
                {"role": "system", "content": system_prompt(POST_MERGE_SYSTEM, cfg)},
                {
                    "role": "user",
                    "content": "### ACTION\n"
                    + untrusted("action", action)
                    + "\n\n"
                    + render_pr_context(pr.title, pr.body, None, files, diff_budget=8000),
                },
            ],
            response_model=MarkdownOutput,
            max_output_tokens=1200,
            trace=trace,
        )
    except StructuredOutputError:
        return "_HootPR could not complete this action._"
    return clean_prose(cast(MarkdownOutput, res.parsed).markdown, OUTPUT_MAX, host)


def run_post_merge(ctx: WorkerContext, provider: str, provider_repo_id: str, number: int) -> str:
    with ctx.session_factory() as s:
        found = find_reviewable_repo(s, provider, provider_repo_id)
        if found is None:
            return "ignored"
        repo, org, _ = found
        if org.credits_balance <= 0:
            return "ignored"
        pr_row = s.execute(
            select(PullRequest).where(PullRequest.repo_id == repo.id, PullRequest.number == number)
        ).scalar_one_or_none()
        platform = ctx.platforms(s, repo)
        try:
            ref = repo_ref(repo)
            live = platform.get_pull_request(ref, number)
            if live.state != "merged":
                return "ignored"
            cfg = load_effective_config(
                platform, ref, live.base_ref, repo.settings, org.settings
            ).config
            if not any_enabled(cfg):
                return "ignored"
            if any(MARKER in c.body for c in platform.list_comments(ref, number) if not c.path):
                return "ignored"  # already done (redelivery)
            findings = open_findings(s, pr_row.id) if pr_row is not None else []
            s.rollback()
            body = _actions(ctx, platform, ref, org.id, live, cfg, findings)
            platform.upsert_comment(ref, number, MARKER, body)
            return "processed"
        finally:
            close_platform(platform)


def _actions(
    ctx: WorkerContext,
    platform: GitPlatform,
    ref: RepoRef,
    org_id: UUID,
    live: PlatformPR,
    cfg: HootPRConfig,
    findings: Sequence[Finding],
) -> str:
    a = cfg.reviews.post_merge_actions
    llm = MeteredLLM(ctx.llm())
    trace = TraceContext(org_id=org_id, stage="post_merge")
    host = repo_host(ref.provider, ctx.settings)
    sections: list[str] = []
    files: list[FileDiff] = []
    if a.changelog.enabled or any(r.enabled for r in a.custom):
        try:
            files = platform.get_diff(ref, live.number)
        except Exception:
            log.warning("post_merge_diff_failed", exc_info=True)
    if a.follow_up_issue.enabled:
        if findings:
            try:
                issue = platform.create_issue(
                    ref,
                    f"Follow-up: unresolved review comments from #{live.number}"[:80],
                    follow_up_body(live, ref.full_name, findings),
                )
                text = f"Opened [#{issue.number}]({issue.url}) for {len(findings)} open comment(s)."
            except Exception:
                log.warning("follow_up_issue_failed", exc_info=True)
                text = "_HootPR could not open the follow-up issue._"
        else:
            text = "No unresolved HootPR comments: no follow-up issue needed."
        sections.append(f"### Follow-up issue\n\n{text}")
    if a.changelog.enabled:
        out = run_recipe(llm, cfg, CHANGELOG_ACTION, live, files, trace=trace, host=host)
        sections.append(f"### Changelog entry\n\n{out}")
    for r in a.custom:
        if r.enabled:
            out = run_recipe(llm, cfg, r.instructions, live, files, trace=trace, host=host)
            name = " ".join(r.name.split()).replace("<", "&lt;")
            sections.append(f"### {name}\n\n{out}")
    return "\n\n".join([MARKER, "## Post-merge actions", *sections])
