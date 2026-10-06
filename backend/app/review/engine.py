"""HootPR review engine (spec §7, plan contract C2).

Platform- and DB-agnostic: the Celery pipeline and the eval suite both call ``run_engine``.
Stage order: diff & filter → sandbox → code graph → static tools → context pack → triage →
plan → agents → judge → summarize, orchestrated as a LangGraph ``StateGraph`` (``review_graph``).
Posting, persistence and credits live in the pipeline.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Literal, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.billing.pricing import BUDGET_HEADROOM
from app.config.schema import HootPRConfig
from app.kb.cross_repo import breaking_change_findings
from app.kb.external import ExternalTools
from app.kb.linked import (
    LinkedGraph,
    LinkedRepoSpec,
    build_linked_graphs,
    clone_linked,
    render_linked_block,
)
from app.knowledge.base import KnowledgeBase, LearningHit, NullKnowledge, render_learnings_block
from app.knowledge.guidelines import (
    Guideline,
    collect_guidelines,
    guidelines_for,
    render_guidelines,
)
from app.llm.gateway import LLMGateway
from app.llm.types import StructuredOutputError, ToolsUnsupported, TraceContext, Usage
from app.logging import get_logger
from app.merge.docstrings import DocstringCoverage, maybe_docstring_coverage
from app.platforms.base import FileDiff, GitPlatform, PullRequest, RepoRef
from app.review.agent import AgentLimits, Toolbox, run_agent
from app.review.anchoring import DiffIndex, fingerprint
from app.review.ast_grep import AstGrepMatch, run_ast_grep
from app.review.cache import NullCache, ReviewCache, cache_key
from app.review.context import FileContext, build_file_context, render_pack
from app.review.findings import Candidate, Severity, rank_key
from app.review.graph import CodeGraph
from app.review.judge_rules import deterministic_judge
from app.review.llm import MeteredLLM
from app.review.safety import harden_candidate, repo_host
from app.review.schemas import PlanTask, WalkthroughSummary
from app.review.stages.diff_filter import SkippedFile, apply_budget, filter_files
from app.review.stages.judge import apply_thresholds, llm_verify, min_confidence
from app.review.stages.planner import plan_review
from app.review.stages.singlepass import single_pass
from app.review.stages.summarize import fallback_summary, summarize
from app.review.stages.triage import TriageOutcome, triage
from app.review.tool_results import ToolResults, ToolRunRecord, enabled_tools, parse_tool_output
from app.review.trace import TraceSink, timed_stage
from app.sandbox.base import (
    ExecResult,
    RepoTooLarge,
    Sandbox,
    SandboxManager,
    repo_size_mb,
    sandbox_session,
)
from app.security.blast_radius import (
    BlastRadius,
    boost_candidates,
    compute_blast_radius,
    render_prompt,
)
from app.settings import Settings

log = get_logger(__name__)
# Characters of the context pack used (with the task title/rationale/files) as the learnings query.
LEARNINGS_QUERY_PACK_CHARS = 4000
# Output caps (KiB) for the sandbox scripts. The graph cap bounds the worker's transient peak while
# parsing (~4-5x the JSON size, spec §11.3 256 MB worker); a bigger graph degrades to "no graph".
GRAPH_MAX_OUTPUT_KB = 16 * 1024
TOOLS_MAX_OUTPUT_KB = 8 * 1024
# run_tools.py gets a global deadline this much shorter than the outer exec timeout so it always
# prints its JSON (slow tools become "timeout") instead of being killed with every result lost.
TOOLS_DEADLINE_MARGIN_S = 30
# Per-review ceiling on candidate findings sent to the judge (x REVIEW_MAX_COMMENTS).
REVIEW_FINDINGS_FACTOR = 3
MAX_DEPENDENCY_FINDINGS = 20
_DEP_SEVERITY: dict[str, Severity] = {"error": "major", "warning": "minor", "info": "nitpick"}


@dataclass(frozen=True)
class Ablation:
    judge: bool = True  # False: skip LLM verification + confidence threshold
    tools: bool = True  # False: skip run_tools (static analysis)
    agent_max_steps: int | None = None  # overrides AGENT_MAX_STEPS (0 = no investigation tools)


@dataclass(frozen=True)
class EngineInputs:
    review_id: UUID
    org_id: UUID | None
    repo: RepoRef
    pr: PullRequest
    base_sha: str  # diff base (PR base, or last reviewed SHA when incremental)
    head_sha: str
    incremental: bool
    config: HootPRConfig
    config_source: str = "default"
    config_warnings: tuple[str, ...] = ()
    prior_fingerprints: frozenset[str] = frozenset()
    # The review's credit hold: agent tasks stop being scheduled past BUDGET_HEADROOM of it.
    credit_budget: Decimal | None = None
    # Phase 7: same-org repositories cloned under /work/linked for cross-repo analysis.
    linked_repos: tuple[LinkedRepoSpec, ...] = ()
    # Phase 6: entry points of the repo's latest stored attack surface map (None: no map yet).
    surface_baseline: tuple[dict[str, Any], ...] | None = None


@dataclass
class EngineDeps:
    platform: GitPlatform
    sandboxes: SandboxManager
    llm: LLMGateway
    trace: TraceSink
    settings: Settings
    cache: ReviewCache = field(default_factory=NullCache)
    ablation: Ablation = field(default_factory=Ablation)
    # The agent's `shell` tool; evals turn it off on the local (host) sandbox.
    agent_shell: bool = True
    # Team learnings (phase 3): SqlKnowledge in the pipeline, InMemoryKnowledge in evals.
    knowledge: KnowledgeBase = field(default_factory=NullKnowledge)
    # Phase 7: allowed MCP tools + web_search, called from the worker (never the sandbox).
    external_tools: ExternalTools | None = None


@dataclass
class EngineResult:
    status: Literal["reviewed", "no_reviewable_files"]
    files: list[FileDiff]
    reviewed_files: list[str]
    skipped: list[SkippedFile]
    tasks: list[PlanTask]
    candidates: list[Candidate]
    inline: list[Candidate]
    additional: list[Candidate]
    summary: WalkthroughSummary
    tool_runs: list[ToolRunRecord]
    degraded: dict[str, Any]
    usage: Usage
    cost_usd: Decimal | None
    models: list[str]
    incremental: bool
    sandbox_peak_mb: int | None
    base_sha: str | None = None  # effective diff base (PR base after an incremental fallback)
    # Metered HootPR credits (rate card), total and per stage (``STAGE_LABELS`` keys).
    credits: Decimal = Decimal(0)
    credits_by_stage: dict[str, Decimal] = field(default_factory=dict)
    learnings_used: list[LearningHit] = field(default_factory=list)  # deduped by id
    guidelines_used: list[str] = field(default_factory=list)  # guideline file paths applied
    # Phase 5: docstring coverage of the changed code (pre-merge check); None when not computed.
    docstring_coverage: DocstringCoverage | None = None
    # Phase 6: entry points reachable from the changed code (None: not computed).
    blast_radius: BlastRadius | None = None


def _why(r: ExecResult) -> str:
    if r.timed_out:
        return "timeout"
    if r.truncated:
        return "output too large"
    if r.exit_code != 0:
        return f"exit {r.exit_code}: {r.stderr.strip()[:200]}"
    return "invalid JSON output"


def _json(r: ExecResult) -> Any | None:
    if not r.ok or r.truncated:
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def dependency_findings(tools: ToolResults, lockfiles: list[str]) -> list[Candidate]:
    """Trivy vulnerabilities in lockfiles (never reviewed line by line, spec §7.1/§7.3) become
    walkthrough notes: they cannot be anchored inline, but a vulnerable bump must be reported."""
    wanted = set(lockfiles)
    out: list[Candidate] = []
    for f in tools.findings:
        if f.tool != "trivy" or f.path not in wanted:
            continue
        c = Candidate(
            path=f.path,
            start_line=None,
            end_line=max(1, f.line),
            severity=_DEP_SEVERITY.get(f.severity, "minor"),
            category="security",
            title=f"Vulnerable dependency: {f.rule_id}"[:80],
            body=f"{f.message}\n\nReported by Trivy (`{f.rule_id}`) for `{f.path}`.",
            evidence=[f.render()],
            confidence=1.0,
            source="tool:trivy",
            verdict="keep",
            reason="dependency vulnerability in a lockfile",
            placement="additional",
        )
        c.fingerprint = fingerprint(f.path, f"{f.rule_id} {f.message}", "security")
        out.append(c)
    return sorted(out, key=rank_key)[:MAX_DEPENDENCY_FINDINGS]


class _Engine:
    def __init__(self, inp: EngineInputs, deps: EngineDeps) -> None:
        self.inp, self.deps, self.s, self.cfg = inp, deps, deps.settings, inp.config
        self.llm = MeteredLLM(deps.llm, credit_budget=inp.credit_budget)
        # A knowledge base that embeds through the gateway is re-bound to the metered client,
        # so learning-retrieval embeddings count toward this review's tokens and cost.
        bind = getattr(deps.knowledge, "bind_embedder", None)
        self.knowledge: KnowledgeBase = bind(self.llm) if callable(bind) else deps.knowledge
        self.degraded: dict[str, Any] = {}
        self.trace = TraceContext(org_id=inp.org_id, review_id=inp.review_id)
        self.incremental = inp.incremental
        self.files: list[FileDiff] = []
        self.kept: list[FileDiff] = []
        self.skipped: list[SkippedFile] = []
        self.lockfiles: list[str] = []
        # Effective diff base: the last reviewed SHA for incremental runs, the PR base otherwise.
        self.base_sha = inp.base_sha
        self.use_cache = not inp.config.reviews.disable_cache
        self.used: dict[str, LearningHit] = {}
        self.guidelines_applied: dict[str, None] = {}  # ordered set of guideline paths
        self.linked_specs: list[LinkedRepoSpec] = []
        self.linked: list[LinkedGraph] = []
        self.blast: BlastRadius | None = None
        self.stack = ExitStack()  # holds the sandbox session between graph nodes

    def learnings(self, task: PlanTask, pack: str) -> list[LearningHit]:
        """Top-k team learnings for one task; a failing knowledge base degrades, never fails."""
        if self.degraded.get("learnings") == "unavailable":
            return []
        query = "\n".join(
            [task.title, task.rationale, " ".join(task.files), pack[:LEARNINGS_QUERY_PACK_CHARS]]
        )
        try:
            hits = self.knowledge.learnings_for(
                query, task.files, k=self.s.learnings_top_k, trace=self.at("learnings")
            )
        except Exception:
            log.warning("learnings_unavailable", exc_info=True)
            self.degraded["learnings"] = "unavailable"
            return []
        for h in hits:
            self.used.setdefault(h.id, h)
        return hits

    def at(self, stage: str) -> TraceContext:
        """The review trace attributed to one credit stage."""
        return replace(self.trace, stage=stage)

    def knowledge_pack(self, task: PlanTask, pack: str, guidelines: list[Guideline]) -> str:
        """The context pack + applicable base-branch guidelines + the team learnings block."""
        applied = guidelines_for(guidelines, task.files)
        for g in applied:
            self.guidelines_applied.setdefault(g.path, None)
        extras = [
            render_guidelines(applied),
            render_learnings_block(self.learnings(task, pack)),
            render_prompt(self.blast, task.files),
        ]
        return "\n\n".join([pack, *(x for x in extras if x)])

    def judge_learnings(self) -> str:
        best = sorted(self.used.values(), key=lambda h: (-h.similarity, h.id))
        return render_learnings_block(best[: self.s.learnings_top_k])

    def context(
        self, sb: Sandbox, graph: CodeGraph, tools: ToolResults
    ) -> tuple[dict[str, FileContext], list[Guideline]]:
        with timed_stage(self.deps.trace, "context") as st:
            # Guidelines and AST-grep rule files come from the PR base, never the head (R16/R17).
            pr_base = self.inp.pr.base_sha
            guidelines, g_why = collect_guidelines(sb, pr_base, self.cfg, self.s)
            if g_why:
                self.degraded["guidelines"] = g_why
            changed_lines = {
                f.path: (None if f.status == "added" else f.changed_new_lines()) for f in self.kept
            }
            ast_matches, a_why = run_ast_grep(sb, self.cfg, pr_base, changed_lines, self.s)
            if a_why:
                self.degraded["ast_grep"] = a_why
            by_path: dict[str, list[AstGrepMatch]] = {}
            for m in ast_matches:
                by_path.setdefault(m.path, []).append(m)
            contexts = {
                f.path: build_file_context(f, graph, tools, self.cfg, by_path.get(f.path, ()))
                for f in self.kept
            }
            if g_why or a_why:
                st.status = "degraded"
            st.detail = (
                f"{len(contexts)} files, {len(guidelines)} guideline files, "
                f"{len(ast_matches)} ast-grep matches"
            )
            return contexts, guidelines

    # --- stages -------------------------------------------------------------------------------
    def diff(self, *, incremental: bool) -> None:
        with timed_stage(self.deps.trace, "diff") as st:
            p, inp = self.deps.platform, self.inp
            if incremental:
                self.files = p.get_diff(
                    inp.repo, inp.pr.number, base_sha=inp.base_sha, head_sha=inp.head_sha
                )
            else:
                self.files = p.get_diff(inp.repo, inp.pr.number)
            fr = filter_files(self.files, self.cfg)
            b = apply_budget(
                fr.kept,
                max_files=self.s.review_max_files,
                max_lines=self.s.review_max_changed_lines,
            )
            self.kept, self.skipped = b.kept, [*fr.skipped, *b.skipped]
            self.lockfiles = [x.path for x in fr.skipped if x.reason == "lockfile"]
            st.detail = f"{len(self.kept)} of {len(self.files)} files reviewable" + (
                " (incremental)" if incremental else ""
            )

    def sandbox(self, sb: Sandbox) -> None:
        with timed_stage(self.deps.trace, "sandbox") as st:
            creds = self.deps.platform.clone_credentials(self.inp.repo)
            # An incremental run also fetches the PR base: it becomes the diff base when the last
            # reviewed SHA turns out not to be an ancestor (force-push/rebase).
            extra = list(dict.fromkeys(x for x in (self.inp.base_sha, self.inp.pr.base_sha) if x))
            sb.clone(creds, self.inp.head_sha, self.s.sandbox_clone_depth, extra_refs=extra)
            if self.inp.linked_repos:  # before sealing: the clones need the network
                self.linked_specs = clone_linked(
                    sb, self.deps.platform, self.inp.linked_repos, self.s, self.degraded
                )
            sb.seal()
            size = repo_size_mb(sb)
            if size > self.s.repo_max_mb:
                raise RepoTooLarge(
                    f"repository checkout is {size} MB (limit {self.s.repo_max_mb} MB)"
                )
            st.detail = f"{size} MB checkout, network sealed"

    def ancestor_ok(self, sb: Sandbox) -> bool:
        r = sb.exec(
            ["git", "merge-base", "--is-ancestor", self.inp.base_sha, self.inp.head_sha],
            timeout_s=30,
            max_output_kb=4,
        )
        return r.exit_code == 0 and not r.timed_out

    def graph(self, sb: Sandbox, changed: list[str]) -> CodeGraph:
        with timed_stage(self.deps.trace, "graph") as st:
            key = cache_key("graph", *sorted(changed))
            data = self.deps.cache.get(self.inp.head_sha, "graph", key) if self.use_cache else None
            cached = data is not None
            if data is None:
                argv = [
                    sb.python,
                    f"{sb.tools_dir}/build_graph.py",
                    "--repo",
                    sb.repo_dir,
                    "--max-files",
                    str(self.s.graph_max_files),
                    "--max-symbols",
                    str(self.s.graph_max_symbols),
                ]
                argv += [a for p in changed for a in ("--changed", p)]
                r = sb.exec(
                    argv,
                    timeout_s=self.s.sandbox_graph_timeout_s,
                    max_output_kb=GRAPH_MAX_OUTPUT_KB,
                )
                data = _json(r)
                if data is None:
                    self.degraded["graph"] = _why(r)
                    st.status, st.detail = "degraded", self.degraded["graph"]
                    return CodeGraph.empty()
                g = CodeGraph.from_json(data)
                del data  # the parsed dicts are the transient peak; the cache stores the raw JSON
                if self.use_cache:
                    self.deps.cache.put_raw(self.inp.head_sha, "graph", key, r.stdout)
                del r
            else:
                g = CodeGraph.from_json(data)
                del data
            st.detail = (
                f"{len(g)} symbols, scope {g.scope}"
                + (" (cached)" if cached else "")
                + (" (truncated)" if g.truncated else "")
            )
            return g

    def tools(self, sb: Sandbox, changed: list[str]) -> ToolResults:
        with timed_stage(self.deps.trace, "tools") as st:
            names = enabled_tools(self.cfg) if self.deps.ablation.tools else []
            if not names:
                st.status, st.detail = "skipped", "no tools enabled"
                return ToolResults()
            tcfg = self.cfg.reviews.tools
            manifests = sorted(self.lockfiles)
            key = cache_key(
                "tools",
                ",".join(names),
                f"base={self.base_sha or ''}",
                f"phpstan={tcfg.phpstan.level}",
                f"semgrep={tcfg.semgrep.config_file or ''}",
                *sorted(changed),
                "--manifests--",
                *manifests,
            )
            data = self.deps.cache.get(self.inp.head_sha, "tools", key) if self.use_cache else None
            cached = data is not None
            if data is None:
                argv = [
                    sb.python,
                    f"{sb.tools_dir}/run_tools.py",
                    "--repo",
                    sb.repo_dir,
                    "--enable",
                    ",".join(names),
                    "--configs",
                    str(PurePosixPath(sb.tools_dir).parent / "configs"),
                    "--phpstan-level",
                    str(tcfg.phpstan.level),
                    "--head",
                    self.inp.head_sha,
                    "--deadline",
                    str(max(30, self.s.sandbox_tools_timeout_s - TOOLS_DEADLINE_MARGIN_S)),
                ]
                if self.base_sha:
                    argv += ["--base", self.base_sha]
                if tcfg.semgrep.config_file:
                    argv += ["--semgrep-config", tcfg.semgrep.config_file]
                argv += [a for p in changed for a in ("--changed", p)]
                argv += [a for p in manifests for a in ("--manifest", p)]
                r = sb.exec(
                    argv,
                    timeout_s=self.s.sandbox_tools_timeout_s,
                    max_output_kb=TOOLS_MAX_OUTPUT_KB,
                )
                data = _json(r)
                if data is None:
                    self.degraded["tools"] = _why(r)
                    st.status, st.detail = "degraded", self.degraded["tools"]
                    return ToolResults()
                if self.use_cache:
                    self.deps.cache.put(self.inp.head_sha, "tools", key, data)
            res = parse_tool_output(data)
            self.deps.trace.tool_runs(res.runs)
            bad = [r.tool for r in res.runs if r.status in ("failed", "timeout")]
            if bad:
                self.degraded["tools"] = f"failed or timed out: {', '.join(bad)}"
                st.status = "degraded"
            st.detail = (
                f"{len(res.findings)} findings from {sum(r.status == 'ok' for r in res.runs)} tools"
                + (" (cached)" if cached else "")
            )
            return res

    def agents(
        self,
        sb: Sandbox,
        tasks: list[PlanTask],
        contexts: dict[str, FileContext],
        graph: CodeGraph,
        tools: ToolResults,
        guidelines: list[Guideline] | None = None,
    ) -> list[Candidate]:
        s, sink = self.s, self.deps.trace
        steps = self.deps.ablation.agent_max_steps
        limits = AgentLimits(
            s.agent_max_steps if steps is None else max(0, steps),
            s.agent_max_input_tokens,
            s.agent_shell_timeout_s,
            s.agent_shell_max_output_kb,
            max_task_input_tokens=s.agent_max_task_input_tokens,
            max_findings=s.agent_max_findings,
            allow_shell=self.deps.agent_shell,
        )
        toolbox = Toolbox(
            sb, graph, tools, limits, linked=self.linked, external=self.deps.external_tools
        )
        out: list[Candidate] = []
        agentic = True
        skipped: list[int] = []
        forced: list[int] = []
        over_budget: list[int] = []
        over_credits: list[int] = []
        with timed_stage(sink, "agents") as st:
            for ordinal, task in enumerate(tasks):
                task_id = sink.task_created(ordinal, task)
                if self.llm.usage.input_tokens >= s.review_max_input_tokens:
                    sink.task_status(task_id, "skipped", "review token budget exhausted")
                    over_budget.append(ordinal)
                    continue
                if self.llm.budget_used(BUDGET_HEADROOM):
                    sink.task_status(task_id, "skipped", "reserved credits reached")
                    over_credits.append(ordinal)
                    continue
                trace = TraceContext(
                    self.inp.org_id, self.inp.review_id, task_id=task_id, stage="agents"
                )
                pack = render_pack(
                    [contexts[p] for p in task.files if p in contexts],
                    budget_chars=s.agent_max_input_tokens * 2,
                )
                pack = self.knowledge_pack(task, pack, guidelines or [])
                if self.linked:
                    pack = f"{pack}\n\n{render_linked_block(self.linked)}"

                def hook(
                    kind: str,
                    tool: str | None,
                    args: dict[str, Any],
                    excerpt: str | None,
                    ms: int | None,
                    _tid: UUID = task_id,
                ) -> None:
                    sink.agent_step(_tid, kind, tool, args, excerpt, ms)

                found: list[Candidate] | None = None
                summary = ""
                try:
                    if agentic:
                        try:
                            outcome = run_agent(
                                self.llm, task, ordinal, pack, toolbox, limits, self.cfg,
                                trace=trace, on_step=hook,
                            )  # fmt: skip
                            found, summary = outcome.findings, outcome.summary
                            if outcome.stop_reason != "done":
                                forced.append(ordinal)
                        except ToolsUnsupported:
                            agentic = False
                            self.degraded["tools_calling"] = False
                    if found is None:
                        found = single_pass(self.llm, task, ordinal, pack, self.cfg, trace=trace)
                        summary = "single-pass review"
                except StructuredOutputError:
                    sink.task_status(task_id, "skipped", "structured output failed")
                    skipped.append(ordinal)
                    continue
                except Exception:
                    sink.task_status(task_id, "failed")
                    raise
                for c in found:
                    c.task_id = task_id
                out += found
                sink.task_status(task_id, "done", summary or None)
            cap = REVIEW_FINDINGS_FACTOR * s.review_max_comments
            if len(out) > cap:
                for c in sorted(out, key=rank_key)[cap:]:
                    c.drop("finding_budget_exhausted")
                self.degraded["findings_capped"] = len(out) - cap
            if skipped:
                self.degraded["tasks_skipped"] = skipped
            if over_budget:
                self.degraded["token_budget"] = over_budget
            if over_credits:
                self.degraded["credit_budget"] = "reached"
            if forced:
                self.degraded["forced_done"] = forced
            if skipped or over_budget or over_credits or not agentic:
                st.status = "degraded"
            st.detail = f"{len(tasks)} tasks, {len(out)} candidate findings" + (
                "" if agentic else " (single-pass)"
            )
        return out

    def judge(
        self, cands: list[Candidate], diff: DiffIndex
    ) -> tuple[list[Candidate], list[Candidate]]:
        with timed_stage(self.deps.trace, "judge") as st:
            host = repo_host(self.inp.repo.provider, self.s)
            alive = [c for c in cands if c.alive and harden_candidate(c, host)]
            survivors = deterministic_judge(alive, diff, self.inp.prior_fingerprints)
            use_llm = self.deps.ablation.judge
            if use_llm and survivors:
                partial = llm_verify(
                    self.llm, survivors, diff, self.cfg,
                    batch_size=self.s.judge_batch_size, trace=self.at("judge"),
                    learnings=self.judge_learnings(),
                )  # fmt: skip
                if partial:
                    self.degraded["judge"] = "partial"
                    st.status = "degraded"
            inline, additional = apply_thresholds(
                survivors,
                profile=self.cfg.reviews.profile,
                min_conf=min_confidence(self.cfg, self.s),
                max_comments=self.s.review_max_comments,
                use_confidence=use_llm,
            )
            st.detail = (
                f"{len(cands)} candidates → {len(inline)} inline, {len(additional)} additional"
            )
            return inline, additional

    def summary_files(self) -> list[FileDiff]:
        """The whole PR's reviewable files: an incremental run reviews only the new commits but
        the walkthrough and the "Summary by HootPR" block always describe the full PR."""
        if not self.incremental:
            return self.kept
        try:
            full = self.deps.platform.get_diff(self.inp.repo, self.inp.pr.number)
        except Exception:
            self.degraded["summary_scope"] = "incremental (full diff unavailable)"
            return self.kept
        fr = filter_files(full, self.cfg)
        b = apply_budget(
            fr.kept, max_files=self.s.review_max_files, max_lines=self.s.review_max_changed_lines
        )
        return b.kept or self.kept

    def result_no_files(self) -> EngineResult:
        return EngineResult(
            "no_reviewable_files", self.files, [], self.skipped, [], [], [], [],
            fallback_summary([], None), [], self.degraded, self.llm.usage, self.llm.cost_usd,
            list(self.llm.models), self.incremental, None, self.base_sha,
            credits=self.llm.credits, credits_by_stage=dict(self.llm.credits_by_stage),
        )  # fmt: skip


# --- orchestration: the review as a LangGraph state machine ----------------------------------
#
#   START → diff ─┬─ no reviewable files ──────────────────────────────────────────► no_files → END
#                 └─ open_sandbox → check_history ─┬─ nothing left after re-diff ──► no_files
#                                                  └─ code_graph → static_tools → context → triage
#                     → plan → agents → close_sandbox → judge → summarize → END
#
# Nodes are thin wrappers over the ``_Engine`` stages, which keep their tracing, metering and
# degradation logic. The engine (dependencies + accumulators) is the LangGraph runtime context;
# the graph state carries the artefacts that flow between stages. The sandbox spans
# open_sandbox…close_sandbox through the engine's ExitStack, which ``run_engine`` always closes.


@dataclass(frozen=True)
class ReviewContext:
    engine: _Engine


class ReviewState(TypedDict, total=False):
    sb: Sandbox
    changed: list[str]
    graph: CodeGraph
    doc_cov: DocstringCoverage | None
    tools: ToolResults
    contexts: dict[str, FileContext]
    guidelines: list[Guideline]
    triage: TriageOutcome
    tasks: list[PlanTask]
    candidates: list[Candidate]
    peak_mb: int | None
    inline: list[Candidate]
    additional: list[Candidate]
    result: EngineResult


ReviewRuntime = Runtime[ReviewContext]
ReviewGraph = CompiledStateGraph[ReviewState, ReviewContext, ReviewState, ReviewState]


def _diff(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e = runtime.context.engine
    e.diff(incremental=e.inp.incremental)
    return {}


def _has_files(state: ReviewState, runtime: ReviewRuntime) -> Literal["review", "no_files"]:
    return "review" if runtime.context.engine.kept else "no_files"


def _no_files(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    return {"result": runtime.context.engine.result_no_files()}


def _open_sandbox(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e, s = runtime.context.engine, runtime.context.engine.s
    sb = e.stack.enter_context(
        sandbox_session(
            e.deps.sandboxes, str(e.inp.review_id), mem_mb=s.sandbox_mem_mb, cpus=s.sandbox_cpus
        )
    )
    e.sandbox(sb)
    return {"sb": sb}


def _check_history(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    """An incremental base that is no longer an ancestor (force-push/rebase) → full review."""
    e, inp = runtime.context.engine, runtime.context.engine.inp
    if inp.incremental and not e.ancestor_ok(state["sb"]):
        e.degraded["incremental"] = "history rewritten (force-push/rebase); full review"
        e.incremental = False
        e.base_sha = inp.pr.base_sha
        e.diff(incremental=False)
    return {}


def _code_graph(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e, sb = runtime.context.engine, state["sb"]
    changed = [f.path for f in e.kept]
    graph = e.graph(sb, changed)
    try:  # phase 6: blast radius (best effort, never fails the review)
        e.blast = compute_blast_radius(graph, e.kept, baseline=e.inp.surface_baseline)
    except Exception:
        log.warning("blast_radius_failed", exc_info=True)
        e.degraded["blast_radius"] = "failed"
    doc_cov = maybe_docstring_coverage(e.cfg, graph, e.kept, sb, e.degraded)
    if e.linked_specs:
        e.linked = build_linked_graphs(sb, e.linked_specs, e.s, e.degraded)
    return {"changed": changed, "graph": graph, "doc_cov": doc_cov}


def _static_tools(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    return {"tools": runtime.context.engine.tools(state["sb"], state["changed"])}


def _context(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e = runtime.context.engine
    contexts, guidelines = e.context(state["sb"], state["graph"], state["tools"])
    return {"contexts": contexts, "guidelines": guidelines}


def _triage(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e = runtime.context.engine
    with timed_stage(e.deps.trace, "triage") as st:
        tri = triage(
            e.llm, e.kept, e.cfg, trace=e.at("triage"), tool_counts=state["tools"].counts_by_path()
        )
        if tri.degraded:
            e.degraded["triage"], st.status = "heuristic", "degraded"
        st.detail = (
            f"deep: {len(tri.paths('deep'))}, light: {len(tri.paths('light'))}, "
            f"skip: {len(tri.paths('skip'))}"
        ) + (f"; skip overridden to light: {', '.join(tri.overridden)}" if tri.overridden else "")
    return {"triage": tri}


def _plan(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e = runtime.context.engine
    with timed_stage(e.deps.trace, "plan") as st:
        tasks, plan_degraded = plan_review(
            e.llm,
            e.kept,
            state["triage"],
            state["graph"],
            state["tools"],
            e.cfg,
            max_tasks=e.s.review_max_tasks,
            trace=e.at("plan"),
        )
        if plan_degraded:
            e.degraded["plan"], st.status = "heuristic", "degraded"
        st.detail = f"{len(tasks)} tasks"
    return {"tasks": tasks}


def _agents(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e = runtime.context.engine
    candidates = e.agents(
        state["sb"],
        state["tasks"],
        state["contexts"],
        state["graph"],
        state["tools"],
        state["guidelines"],
    )
    candidates += breaking_change_findings(e.kept, state["graph"], e.linked)
    return {"candidates": candidates}


def _close_sandbox(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    """Judge and summary need no sandbox: release it before the remaining LLM calls."""
    peak = state["sb"].peak_memory_mb()
    runtime.context.engine.stack.close()
    return {"peak_mb": peak}


def _judge(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e, candidates = runtime.context.engine, state["candidates"]
    boosted = boost_candidates(candidates, e.blast)
    if boosted:
        log.info("blast_radius_boost", findings=boosted)
    inline, additional = e.judge(candidates, DiffIndex(e.kept))
    host = repo_host(e.inp.repo.provider, e.s)
    deps_found = [
        c for c in dependency_findings(state["tools"], e.lockfiles) if harden_candidate(c, host)
    ]
    return {
        "candidates": [*candidates, *deps_found],
        "inline": inline,
        "additional": [*additional, *deps_found],
    }


def _summarize(state: ReviewState, runtime: ReviewRuntime) -> ReviewState:
    e, inp = runtime.context.engine, runtime.context.engine.inp
    tri, tasks = state["triage"], state["tasks"]
    inline, additional = state["inline"], state["additional"]
    with timed_stage(e.deps.trace, "summarize") as st:
        summary, sum_degraded = summarize(
            e.llm, e.summary_files(), tri, tasks, [*inline, *additional], e.cfg, inp.pr,
            trace=e.at("summarize"), host=repo_host(inp.repo.provider, e.s),
        )  # fmt: skip
        if sum_degraded:
            e.degraded["summary"], st.status = "fallback", "degraded"
    reviewed = [p for p in state["changed"] if tri.decisions.get(p) != "skip"]
    result = EngineResult(
        "reviewed", e.files, reviewed, e.skipped, tasks, state["candidates"], inline, additional,
        summary, list(state["tools"].runs), e.degraded, e.llm.usage, e.llm.cost_usd,
        list(e.llm.models), e.incremental, state["peak_mb"], e.base_sha,
        credits=e.llm.credits, credits_by_stage=dict(e.llm.credits_by_stage),
        learnings_used=list(e.used.values()), guidelines_used=list(e.guidelines_applied),
        docstring_coverage=state["doc_cov"], blast_radius=e.blast,
    )  # fmt: skip
    return {"result": result}


def build_review_graph() -> ReviewGraph:
    g = StateGraph(ReviewState, context_schema=ReviewContext)
    g.add_node("diff", _diff)
    g.add_node("no_files", _no_files)
    g.add_node("open_sandbox", _open_sandbox)
    g.add_node("check_history", _check_history)
    g.add_node("code_graph", _code_graph)
    g.add_node("static_tools", _static_tools)
    g.add_node("context", _context)
    g.add_node("triage", _triage)
    g.add_node("plan", _plan)
    g.add_node("agents", _agents)
    g.add_node("close_sandbox", _close_sandbox)
    g.add_node("judge", _judge)
    g.add_node("summarize", _summarize)
    g.add_edge(START, "diff")
    g.add_conditional_edges("diff", _has_files, {"review": "open_sandbox", "no_files": "no_files"})
    g.add_edge("open_sandbox", "check_history")
    g.add_conditional_edges(
        "check_history", _has_files, {"review": "code_graph", "no_files": "no_files"}
    )
    for a, b in [
        ("code_graph", "static_tools"),
        ("static_tools", "context"),
        ("context", "triage"),
        ("triage", "plan"),
        ("plan", "agents"),
        ("agents", "close_sandbox"),
        ("close_sandbox", "judge"),
        ("judge", "summarize"),
    ]:
        g.add_edge(a, b)
    g.add_edge("summarize", END)
    g.add_edge("no_files", END)
    return g.compile(name="hootpr-review")


review_graph = build_review_graph()


def run_engine(inp: EngineInputs, deps: EngineDeps) -> EngineResult:
    e = _Engine(inp, deps)
    with e.stack:  # the sandbox is destroyed even when a node raises
        out = review_graph.invoke({}, context=ReviewContext(e))
    result: EngineResult = out["result"]
    return result
