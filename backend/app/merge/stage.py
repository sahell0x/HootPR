"""The review pipeline's Phase 5 stage (spec §10.2): linked issues, pre-merge checks, slop
detection and related PRs, run after the engine and before posting. Never fails a review: every
part degrades to "not shown" and is logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid_utils.compat import uuid7

from app.chat.identity import bot_identity, primary_mention
from app.config.schema import HootPRConfig
from app.knowledge.learnings import effective_scope
from app.llm.types import TraceContext
from app.logging import get_logger
from app.merge.checks import (
    CheckResult,
    any_blocking,
    docstring_check,
    issue_check,
    llm_checks,
    mark_ignored,
    render_pre_merge,
)
from app.merge.context import web_host
from app.merge.embeddings import (
    Similar,
    pr_text,
    purge_embeddings,
    related_prs,
    upsert_pr_embedding,
)
from app.merge.issue_refs import parse_issue_refs
from app.merge.linked_issues import (
    LinkedIssue,
    assess_linked_issues,
    fetch_linked_issues,
    render_linked_issues,
)
from app.merge.slop import SlopResult, detect_slop, render_slop_note
from app.models import IssueLink, Organization, PreMergeResult, Repository
from app.models.base import utcnow
from app.platforms.base import GitPlatform, PullRequest, RepoRef
from app.review.engine import EngineResult
from app.review.llm import MeteredLLM
from app.review.safety import repo_host
from app.worker.context import WorkerContext

log = get_logger(__name__)
RELATED_MAX = 3


@dataclass
class MergeStage:
    checks: list[CheckResult] = field(default_factory=list)
    issues: list[LinkedIssue] = field(default_factory=list)
    slop: SlopResult = field(default_factory=SlopResult)
    related: list[Similar] = field(default_factory=list)
    pr_vector: list[float] | None = None
    sections: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any_blocking(self.checks)


def render_related(related: list[Similar], own_repo: str) -> str:
    if not related:
        return ""
    lines = ["## Possibly related PRs", ""]
    for r in related:
        ref = f"#{r.number}" if r.repo_full_name == own_repo else f"{r.repo_full_name}#{r.number}"
        title = " ".join(r.title.split()).replace("|", "\\|")[:120]
        lines.append(f"- {ref}: {title} (similarity {r.similarity:.2f})")
    return "\n".join([*lines, ""])


def _prior_ignore(s: Session, pr_id: UUID) -> str | None:
    """``@hootpr ignore pre-merge checks`` is sticky for the PR: who ignored them, if anyone."""
    row = s.execute(
        select(PreMergeResult.ignored_by)
        .where(PreMergeResult.pr_id == pr_id, PreMergeResult.ignored.is_(True))
        .order_by(PreMergeResult.created_at.desc())
        .limit(1)
    ).first()
    return (row[0] or "") if row is not None else None


def _allow_foreign(s: Session, org_id: UUID, repo: Repository) -> Any:
    def allow(full_name: str) -> bool:
        other = s.execute(
            select(Repository).where(
                Repository.org_id == org_id,
                Repository.provider == repo.provider,
                Repository.full_name == full_name,
            )
        ).scalar_one_or_none()
        # Never copy private issue content into a public repository's PR.
        return other is not None and (repo.private or not other.private)

    return allow


def run_merge_stage(
    ctx: WorkerContext,
    s: Session,
    platform: GitPlatform,
    ref: RepoRef,
    repo: Repository,
    org: Organization,
    pr_id: UUID,
    review_id: UUID,
    live: PullRequest,
    result: EngineResult,
    cfg: HootPRConfig,
) -> MergeStage:
    """``cfg`` is the engine config (``knowledge_base.opt_out`` already folded in). LLM usage is
    added to ``result`` so the review's tokens/cost include it."""
    st = MergeStage()
    llm = MeteredLLM(ctx.llm())
    trace = TraceContext(org_id=org.id, review_id=review_id, stage="merge_checks")
    host = repo_host(ref.provider, ctx.settings)
    opted_out = cfg.knowledge_base.opt_out or org.knowledge_base_opt_out
    pm = cfg.reviews.pre_merge_checks
    files = result.files
    try:
        want_issues = cfg.reviews.assess_linked_issues or pm.issue_assessment.mode != "off"
        if want_issues:
            refs = parse_issue_refs(live.body, ref.full_name, web_host(ref.provider, ctx.settings))
            st.issues = fetch_linked_issues(platform, ref, refs, _allow_foreign(s, org.id, repo))
            assess_linked_issues(
                llm,
                st.issues,
                live.title,
                live.body,
                result.summary,
                files,
                cfg,
                trace=trace,
                host=host,
            )
    except Exception:
        log.warning("linked_issues_failed", exc_info=True)
        st.issues = []
    try:
        checks = llm_checks(
            llm, cfg, live.title, live.body, result.summary, files, trace=trace, host=host
        )
        for extra in (docstring_check(cfg, result.docstring_coverage), issue_check(cfg, st.issues)):
            if extra is not None:
                checks.append(extra)
        ignored_by = _prior_ignore(s, pr_id)
        if ignored_by is not None:
            checks = mark_ignored(checks, ignored_by or "")
        st.checks = checks
    except Exception:
        log.warning("pre_merge_checks_failed", exc_info=True)
        st.checks = []
    try:
        st.slop = detect_slop(llm, cfg, live.title, live.body, files, trace=trace, host=host)
    except Exception:
        log.warning("slop_detection_failed", exc_info=True)
    if opted_out:
        try:
            purge_embeddings(s, org.id, None if org.knowledge_base_opt_out else repo.id)
            s.commit()
        except Exception:
            s.rollback()
            log.warning("embedding_purge_failed", exc_info=True)
    else:
        try:
            summary = result.summary.pr_summary or result.summary.walkthrough
            [st.pr_vector] = llm.embed([pr_text(live.title, summary)], trace)
            if cfg.reviews.related_prs:
                mode = effective_scope(cfg.knowledge_base.pull_requests.scope, repo.private)
                st.related = related_prs(
                    s,
                    org_id=org.id,
                    repo_id=repo.id,
                    pr_id=pr_id,
                    vector=st.pr_vector,
                    embed_model=ctx.settings.llm_embed_model,
                    mode=mode,
                    private=repo.private,
                    k=RELATED_MAX,
                    min_similarity=ctx.settings.related_prs_min_similarity,
                )
            s.rollback()  # read-only so far: no transaction stays open while posting
        except Exception:
            s.rollback()
            log.warning("related_prs_failed", exc_info=True)
    mention = primary_mention(bot_identity(ctx.settings, ref.provider, None))
    if cfg.reviews.assess_linked_issues:
        st.sections.append(render_linked_issues(st.issues))
    st.sections.append(render_related(st.related, ref.full_name))
    st.sections.append(render_slop_note(st.slop))
    st.sections.append(render_pre_merge(st.checks, mention))
    st.sections = [x for x in st.sections if x]
    result.usage = result.usage + llm.usage
    if llm.cost_usd is not None:
        result.cost_usd = (result.cost_usd or 0) + llm.cost_usd
    for m in llm.models:
        if m not in result.models:
            result.models.append(m)
    result.credits += llm.credits
    for k, v in llm.credits_by_stage.items():
        result.credits_by_stage[k] = result.credits_by_stage.get(k, Decimal(0)) + v
    return st


def persist_merge_stage(
    ctx: WorkerContext,
    s: Session,
    platform: GitPlatform,
    ref: RepoRef,
    repo: Repository,
    org: Organization,
    pr_id: UUID,
    review_id: UUID,
    live: PullRequest,
    result: EngineResult,
    cfg: HootPRConfig,
    st: MergeStage,
) -> None:
    """After posting: store results/links/embedding and add the slop label (best effort)."""
    try:
        for c in st.checks:
            s.add(
                PreMergeResult(
                    pr_id=pr_id,
                    review_id=review_id,
                    head_sha=live.head_sha[:64],
                    kind=c.kind,
                    name=c.name[:128],
                    mode=c.mode,
                    status=c.status,
                    explanation=c.explanation[:4000],
                    ignored=c.ignored,
                    ignored_by=c.ignored_by,
                )
            )
        now = utcnow()
        for i in st.issues:
            values = {
                "url": (i.issue.url if i.issue else "")[:1024],
                "title": (i.issue.title if i.issue else "")[:512],
                "assessment": i.overall[:16],
                "explanation": "; ".join(f"{o.status}: {o.text}" for o in i.objectives)[:4000]
                or i.note,
                "head_sha": live.head_sha[:64],
                "updated_at": now,
            }
            s.execute(
                insert(IssueLink)
                .values(
                    id=uuid7(),
                    created_at=now,
                    pr_id=pr_id,
                    issue_repo=i.repo[:512],
                    issue_number=i.ref.number,
                    **values,
                )
                .on_conflict_do_update(
                    index_elements=["pr_id", "issue_repo", "issue_number"], set_=values
                )
            )
        if st.pr_vector is not None:
            upsert_pr_embedding(
                s,
                org_id=org.id,
                repo_id=repo.id,
                pr_id=pr_id,
                number=live.number,
                title=live.title,
                url=live.url,
                summary=result.summary.pr_summary or result.summary.walkthrough,
                vector=st.pr_vector,
                model=ctx.settings.llm_embed_model,
            )
        s.commit()
    except Exception:
        s.rollback()
        log.exception("merge_stage_persist_failed")
    label = cfg.reviews.slop_detection.label.strip()
    if st.slop.flagged and label and label not in live.labels:
        try:
            platform.add_labels(ref, live.number, [label], merge_request=True)
        except Exception:
            log.warning("slop_label_failed", exc_info=True)
