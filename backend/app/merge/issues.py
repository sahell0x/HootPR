"""Issue enrichment on ``issues.opened`` (spec §10.2): possible duplicates (issue embeddings),
suggested labels (cheap model) and suggested assignees (CODEOWNERS + recent committers), posted as
one comment on the issue. Free of charge; skipped for blocked orgs and orgs without credits."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from sqlalchemy.orm import Session

from app.config.loader import load_effective_config
from app.config.schema import HootPRConfig
from app.events.models import IssueOpened
from app.knowledge.learnings import effective_scope
from app.llm.types import StructuredOutputError, TraceContext
from app.logging import get_logger
from app.merge.codeowners import (
    CODEOWNERS_PATHS,
    owners_for,
    parse_codeowners,
    paths_in_text,
    user_owners,
)
from app.merge.embeddings import (
    Similar,
    issue_text,
    purge_embeddings,
    similar_issues,
    upsert_issue_embedding,
)
from app.merge.prompts import ISSUE_LABELS_SYSTEM
from app.merge.schemas import LabelSuggestion
from app.models import Organization, Repository
from app.platforms.base import GitPlatform, RepoRef
from app.platforms.factory import close_platform, repo_ref
from app.review.llm import LLMLike, MeteredLLM
from app.review.pipeline import find_reviewable_repo
from app.review.prompts import system_prompt
from app.review.safety import clean_prose, repo_host, untrusted
from app.worker.context import WorkerContext

log = get_logger(__name__)
MARKER = "<!-- hootpr:issue-enrichment -->"
MAX_DUPLICATES = 3
MAX_LABELS = 3
MAX_ASSIGNEES = 3
MAX_PATHS = 3


@dataclass
class Enrichment:
    duplicates: list[Similar] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    labels_applied: bool = False
    label_reason: str = ""
    assignees: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.duplicates or self.labels or self.assignees)


def suggest_labels(
    llm: LLMLike,
    cfg: HootPRConfig,
    title: str,
    body: str,
    allowed: dict[str, str],
    *,
    trace: TraceContext,
    host: str | None,
) -> tuple[list[str], str]:
    if not allowed:
        return [], ""
    listing = "\n".join(f"- {name}" + (f": {why}" if why else "") for name, why in allowed.items())
    try:
        res = llm.complete(
            "cheap",
            [
                {"role": "system", "content": system_prompt(ISSUE_LABELS_SYSTEM, cfg)},
                {
                    "role": "user",
                    "content": "Allowed labels:\n"
                    + untrusted("labels", listing)
                    + "\n\n"
                    + untrusted("issue", f"title: {title}\n\n{body[:4000]}"),
                },
            ],
            response_model=LabelSuggestion,
            max_output_tokens=300,
            trace=trace,
        )
    except StructuredOutputError:
        return [], ""
    out = cast(LabelSuggestion, res.parsed)
    by_lower = {k.lower(): k for k in allowed}
    labels = list(dict.fromkeys(by_lower[x.lower()] for x in out.labels if x.lower() in by_lower))
    return labels[:MAX_LABELS], clean_prose(" ".join(out.reason.split()), 300, host)


def suggest_assignees(
    platform: GitPlatform, ref: RepoRef, default_branch: str, text: str, author: str
) -> list[str]:
    paths = paths_in_text(text, MAX_PATHS)
    out: list[str] = []
    rules = []
    for loc in CODEOWNERS_PATHS:
        content = platform.get_file(ref, loc, default_branch)
        if content:
            rules = parse_codeowners(content)
            break
    for p in paths:
        out += user_owners(owners_for(rules, p))
    targets: list[str | None] = list(paths) or [None]
    for target in targets:
        try:
            out += platform.recent_committers(ref, target, limit=MAX_ASSIGNEES)
        except Exception:
            log.warning("recent_committers_failed", exc_info=True)
    seen = [u for u in dict.fromkeys(out) if u.lower() != author.lower()]
    return seen[:MAX_ASSIGNEES]


def render_enrichment(e: Enrichment, own_repo: str) -> str:
    lines = [MARKER, "## HootPR issue triage", ""]
    if e.duplicates:
        lines += ["### Possible duplicates", ""]
        for d in e.duplicates:
            ref = (
                f"#{d.number}" if d.repo_full_name == own_repo else f"{d.repo_full_name}#{d.number}"
            )
            title = " ".join(d.title.split())[:120]
            lines.append(f"- {ref}: {title} ({d.state}, similarity {d.similarity:.2f})")
        lines.append("")
    if e.labels:
        verb = "Applied labels" if e.labels_applied else "Suggested labels"
        lines += [f"### {verb}", "", ", ".join(f"`{x}`" for x in e.labels)]
        if e.label_reason:
            lines += ["", f"_{e.label_reason}_"]
        lines.append("")
    if e.assignees:
        # Backticked so the suggestion does not notify anyone.
        lines += ["### Suggested assignees", "", ", ".join(f"`{u}`" for u in e.assignees), ""]
    return "\n".join(
        [
            *lines,
            "---",
            "Tip: HootPR enriches new issues; configure it under "
            "`issue_enrichment` in `.hootpr.yaml`.",
        ]
    )


def enrich_issue(ctx: WorkerContext, ev: IssueOpened) -> str:
    with ctx.session_factory() as s:
        found = find_reviewable_repo(s, ev.provider, ev.repo.provider_repo_id)
        if found is None:
            return "ignored"
        repo, org, _ = found
        if org.credits_balance <= 0:
            log.info("issue_enrichment_skipped", reason="no_credits")
            return "ignored"
        platform = ctx.platforms(s, repo)
        try:
            return _enrich(ctx, s, platform, repo, org, ev)
        finally:
            close_platform(platform)


def _enrich(
    ctx: WorkerContext,
    s: Session,
    platform: GitPlatform,
    repo: Repository,
    org: Organization,
    ev: IssueOpened,
) -> str:
    ref = repo_ref(repo)
    cfg = load_effective_config(
        platform, ref, repo.default_branch, repo.settings, org.settings
    ).config
    if not cfg.issue_enrichment.auto_enrich.enabled:
        return "ignored"
    llm = MeteredLLM(ctx.llm())
    trace = TraceContext(org_id=org.id, stage="issue_enrichment")
    host = repo_host(ref.provider, ctx.settings)
    e = Enrichment()
    opted_out = cfg.knowledge_base.opt_out or org.knowledge_base_opt_out
    if opted_out:
        purge_embeddings(s, org.id, None if org.knowledge_base_opt_out else repo.id)
        s.commit()
    else:
        try:
            [vec] = llm.embed([issue_text(ev.title, ev.body)], trace)
            mode = effective_scope(cfg.knowledge_base.issues.scope, repo.private)
            e.duplicates = similar_issues(
                s,
                org_id=org.id,
                repo_id=repo.id,
                exclude_number=ev.number,
                vector=vec,
                embed_model=ctx.settings.llm_embed_model,
                mode=mode,
                private=repo.private,
                k=MAX_DUPLICATES,
                min_similarity=ctx.settings.issue_duplicate_min_similarity,
            )
            upsert_issue_embedding(
                s,
                org_id=org.id,
                repo_id=repo.id,
                number=ev.number,
                title=ev.title,
                url=ev.url,
                state="open",
                vector=vec,
                model=ctx.settings.llm_embed_model,
            )
            s.commit()
        except Exception:
            s.rollback()
            log.warning("issue_duplicates_failed", exc_info=True)
    try:
        lab = cfg.issue_enrichment.labeling
        allowed = {x.label: x.instructions for x in lab.labeling_instructions} or {
            name: "" for name in platform.list_labels(ref)
        }
        allowed = {k: v for k, v in allowed.items() if k not in ev.labels}
        e.labels, e.label_reason = suggest_labels(
            llm, cfg, ev.title, ev.body, allowed, trace=trace, host=host
        )
        if e.labels and lab.auto_apply_labels:
            platform.add_labels(ref, ev.number, e.labels)
            e.labels_applied = True
    except Exception:
        log.warning("issue_labels_failed", exc_info=True)
    try:
        e.assignees = suggest_assignees(
            platform, ref, repo.default_branch, f"{ev.title}\n{ev.body}", ev.author_username
        )
    except Exception:
        log.warning("issue_assignees_failed", exc_info=True)
    if e.empty:
        return "processed"
    platform.comment_on_issue(ref, ev.number, render_enrichment(e, ref.full_name))
    log.info(
        "issue_enriched",
        duplicates=len(e.duplicates),
        labels=len(e.labels),
        assignees=len(e.assignees),
    )
    return "processed"
