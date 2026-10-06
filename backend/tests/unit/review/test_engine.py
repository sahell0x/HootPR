import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from uuid_utils.compat import uuid7

from app.config.schema import HootPRConfig
from app.llm.types import ProviderUnavailable
from app.platforms.base import PullRequest, RepoRef
from app.platforms.local import LocalPlatform
from app.review.cache import cache_key
from app.review.engine import Ablation, EngineDeps, EngineInputs, run_engine
from app.review.trace import InMemoryTraceSink
from app.sandbox.base import RepoTooLarge
from app.sandbox.local import LocalSandboxManager
from app.settings import Settings
from tests.fakes.engine_llm import EngineFakeLLM, make_test_gateway
from tests.fakes.sandbox import FakeSandboxManager
from tests.helpers_git import make_git_repo, write_stub_tools

REF = RepoRef("github", "1", "acme/web")
BASE = {"app/db.py": "def get(conn, uid):\n    return conn.execute('select 1')\n"}
HEAD = {
    "app/db.py": "def get(conn, uid):\n    return conn.execute(f'select * from u where id={uid}')\n"
}
SQLI: dict[str, Any] = {
    "path": "app/db.py",
    "start_line": None,
    "end_line": 2,
    "severity": "critical",
    "category": "security",
    "title": "SQL injection",
    "confidence": 0.95,
}


@dataclass
class Harness:
    fake: EngineFakeLLM
    sink: InMemoryTraceSink
    deps: EngineDeps
    inputs: EngineInputs
    tmp: Path


def harness(
    tmp_path: Path,
    settings: Settings,
    *,
    base: dict[str, str] = BASE,
    head: dict[str, str | None] | None = None,
    fake: EngineFakeLLM | None = None,
    graph: dict[str, Any] | None = None,
    tools: dict[str, Any] | None = None,
    tools_dir: Path | None = None,
    **inputs_kw: Any,
) -> Harness:
    repo = make_git_repo(tmp_path / "src", base, head if head is not None else dict(HEAD))
    lp = LocalPlatform()
    pr = PullRequest(
        7,
        "Fix query",
        "",
        "alice",
        "open",
        False,
        "main",
        "f",
        repo.base_sha,
        repo.head_sha,
        (),
        "",
    )
    lp.add_pull_request(REF, pr, repo.files)
    lp.register_repo_path(REF, repo.path)
    fake = fake or EngineFakeLLM()
    gw, _ = make_test_gateway(fake)
    sink = InMemoryTraceSink()
    tdir = tools_dir or write_stub_tools(tmp_path / "tools", graph, tools)
    deps = EngineDeps(lp, LocalSandboxManager(tdir, base_dir=tmp_path), gw, sink, settings)
    kw: dict[str, Any] = dict(
        review_id=uuid7(),
        org_id=None,
        repo=REF,
        pr=pr,
        base_sha=repo.base_sha,
        head_sha=repo.head_sha,
        incremental=False,
        config=HootPRConfig(),
    )
    kw.update(inputs_kw)
    return Harness(fake, sink, deps, EngineInputs(**kw), tmp_path)


def test_engine_reviews_changed_code_end_to_end(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings)
    h.fake.findings = [SQLI, {"path": "app/db.py", "end_line": 40, "title": "Far away"}]
    res = run_engine(h.inputs, h.deps)
    assert res.status == "reviewed" and res.reviewed_files == ["app/db.py"]
    assert [c.title for c in res.inline] == ["SQL injection"]
    far = next(c for c in res.candidates if c.title == "Far away")
    assert (far.verdict, far.reason) == ("drop", "outside_changed_hunk")
    assert [s.name for s in h.sink.stages] == [
        "diff", "sandbox", "graph", "tools", "context", "triage",
        "plan", "agents", "judge", "summarize",
    ]  # fmt: skip
    assert {s.status for s in h.sink.stages} == {"ok"}
    assert [t["status"] for t in h.sink.tasks.values()] == ["done"]
    assert {"TriageResult", "ReviewPlan", "agent", "JudgeBatch", "WalkthroughSummary"} <= set(
        h.fake.stages
    )
    assert res.usage.input_tokens > 0 and set(res.models) == {"model-review", "model-cheap"}
    assert res.inline[0].task_id in h.sink.tasks
    assert res.incremental is False and res.tasks[0].files == ["app/db.py"]
    assert any(st["kind"] == "tool_call" for st in h.sink.steps)
    assert not list(tmp_path.glob("hootpr-*"))  # sandbox destroyed


def test_pr_with_only_lockfiles_needs_no_sandbox(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings, base={"pnpm-lock.yaml": "a\n"}, head={"pnpm-lock.yaml": "b\n"})
    res = run_engine(h.inputs, h.deps)
    assert res.status == "no_reviewable_files" and res.skipped[0].reason == "lockfile"
    assert h.fake.stages == [] and [s.name for s in h.sink.stages] == ["diff"]
    assert not list(tmp_path.glob("hootpr-*"))


def test_provider_without_tools_uses_single_pass(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings, fake=EngineFakeLLM(tools=False))
    h.fake.findings = [SQLI]
    res = run_engine(h.inputs, h.deps)
    assert res.degraded["tools_calling"] is False and "SinglePassFindings" in h.fake.stages
    assert [c.title for c in res.inline] == ["SQL injection"]
    assert next(s for s in h.sink.stages if s.name == "agents").status == "degraded"


def test_graph_script_failure_is_degraded_not_fatal(tmp_path: Path, settings: Settings) -> None:
    tdir = write_stub_tools(tmp_path / "tools")
    (tdir / "build_graph.py").write_text("import sys\nsys.stderr.write('kaboom')\nsys.exit(1)\n")
    h = harness(tmp_path, settings, tools_dir=tdir)
    res = run_engine(h.inputs, h.deps)
    assert res.status == "reviewed" and res.degraded["graph"].startswith("exit 1")
    assert next(s for s in h.sink.stages if s.name == "graph").status == "degraded"


def test_static_findings_reach_the_agent_and_the_trace(tmp_path: Path, settings: Settings) -> None:
    tools = {
        "version": 1,
        "runs": [
            {"tool": "ruff", "status": "ok", "duration_ms": 5, "findings_count": 1,
             "stderr_excerpt": ""}
        ],
        "findings": [
            {"tool": "ruff", "rule_id": "S608", "path": "app/db.py", "line": 2, "end_line": 2,
             "severity": "error", "message": "Possible SQL injection"}
        ],
    }  # fmt: skip
    h = harness(tmp_path, settings, tools=tools)
    res = run_engine(h.inputs, h.deps)
    agent_req = next(r for r in h.fake.requests if r["body"].get("tools"))
    assert "[ruff:S608]" in agent_req["body"]["messages"][1]["content"]
    assert [r.tool for r in h.sink.runs] == ["ruff"] and res.tool_runs[0].findings_count == 1
    assert res.inline == []  # tool findings are never posted raw


def test_ablation_tools_off_skips_run_tools(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings)
    h.deps.ablation = Ablation(tools=False)
    res = run_engine(h.inputs, h.deps)
    tools_stage = next(s for s in h.sink.stages if s.name == "tools")
    assert tools_stage.status == "skipped" and res.tool_runs == []


def test_incremental_falls_back_to_full_when_history_rewritten(
    tmp_path: Path, settings: Settings
) -> None:
    h = harness(tmp_path, settings, incremental=True, base_sha="d" * 40)
    res = run_engine(h.inputs, h.deps)
    assert res.incremental is False and "history rewritten" in res.degraded["incremental"]
    assert [s.name for s in h.sink.stages][:3] == ["diff", "sandbox", "diff"]


def test_incremental_review_stays_incremental_when_base_is_ancestor(
    tmp_path: Path, settings: Settings
) -> None:
    h = harness(tmp_path, settings, incremental=True)
    res = run_engine(h.inputs, h.deps)
    assert res.incremental is True and "incremental" not in res.degraded


def test_second_run_with_prior_fingerprints_posts_nothing_new(
    tmp_path: Path, settings: Settings
) -> None:
    h = harness(tmp_path, settings)
    h.fake.findings = [SQLI]
    first = run_engine(h.inputs, h.deps)
    prior = frozenset(c.fingerprint for c in first.inline)
    h2 = harness(tmp_path / "again", settings, prior_fingerprints=prior)
    h2.fake.findings = [SQLI]
    second = run_engine(h2.inputs, h2.deps)
    assert second.inline == [] and second.candidates[0].reason == "already_posted"


def test_ablation_judge_off_skips_the_llm_judge_and_confidence(
    tmp_path: Path, settings: Settings
) -> None:
    h = harness(tmp_path, settings)
    h.fake.findings = [{**SQLI, "confidence": 0.1}]
    h.deps.ablation = Ablation(judge=False)
    res = run_engine(h.inputs, h.deps)
    assert "JudgeBatch" not in h.fake.stages and [c.title for c in res.inline] == ["SQL injection"]


def test_graph_and_tools_are_cached_per_sha(tmp_path: Path, settings: Settings) -> None:
    class DictCache:
        def __init__(self) -> None:
            self.data: dict[tuple[str, str, str], Any] = {}

        def get(self, sha: str, kind: str, key: str) -> Any | None:
            return self.data.get((sha, kind, key))

        def put(self, sha: str, kind: str, key: str, payload: Any) -> None:
            self.data[(sha, kind, key)] = payload

        def put_raw(self, sha: str, kind: str, key: str, json_text: str) -> None:
            self.data[(sha, kind, key)] = json.loads(json_text)

    h = harness(tmp_path, settings)
    cache = DictCache()
    h.deps.cache = cache
    run_engine(h.inputs, h.deps)
    assert {k[1] for k in cache.data} == {"graph", "tools"}
    assert (h.inputs.head_sha, "graph", cache_key("graph", "app/db.py")) in cache.data
    h.sink.stages.clear()
    run_engine(h.inputs, h.deps)
    graph = next(s for s in h.sink.stages if s.name == "graph")
    assert graph.detail is not None and "(cached)" in graph.detail
    # reviews.disable_cache bypasses the cache entirely
    h.sink.stages.clear()
    cache.data.clear()
    nocache = HootPRConfig.model_validate({"reviews": {"disable_cache": True}})
    run_engine(EngineInputs(**{**h.inputs.__dict__, "config": nocache}), h.deps)
    assert cache.data == {}


def test_repo_too_large_and_provider_down_raise(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path / "big", settings)
    h.deps.settings = settings.model_copy(update={"repo_max_mb": 0})
    with pytest.raises(RepoTooLarge):
        run_engine(h.inputs, h.deps)
    assert next(s for s in h.sink.stages if s.name == "sandbox").status == "failed"
    h2 = harness(tmp_path / "down", settings)
    h2.fake.fail_500 = 99
    with pytest.raises(ProviderUnavailable):
        run_engine(h2.inputs, h2.deps)
    assert not list((tmp_path / "down").glob("hootpr-*"))  # destroyed even on failure
    assert not list((tmp_path / "big").glob("hootpr-*"))


class DictCache:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str, str], Any] = {}

    def get(self, sha: str, kind: str, key: str) -> Any | None:
        return self.data.get((sha, kind, key))

    def put(self, sha: str, kind: str, key: str, payload: Any) -> None:
        self.data[(sha, kind, key)] = payload

    def put_raw(self, sha: str, kind: str, key: str, json_text: str) -> None:
        self.data[(sha, kind, key)] = json.loads(json_text)


def _argv(mgr: FakeSandboxManager, script: str) -> list[str]:
    return next(c for sb in mgr.created for c in sb.calls if any(script in a for a in c))


def _flag(argv: list[str], name: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == name]


TRIVY_LOCK = {
    "version": 1,
    "runs": [{"tool": "trivy", "status": "ok", "duration_ms": 5, "findings_count": 1,
              "stderr_excerpt": ""}],
    "findings": [
        {"tool": "trivy", "rule_id": "CVE-2024-0001", "path": "poetry.lock", "line": 1,
         "end_line": 1, "severity": "error",
         "message": "requests 2.0.0: bad (fixed in 2.32.0)"}
    ],
}  # fmt: skip


def test_lockfile_cves_reach_trivy_and_the_walkthrough(tmp_path: Path, settings: Settings) -> None:
    head = {**HEAD, "poetry.lock": "requests 2.0.0\n"}
    h = harness(tmp_path, settings, base={**BASE, "poetry.lock": "requests 2.32\n"}, head=head)
    mgr = FakeSandboxManager(tools=TRIVY_LOCK)
    h.deps.sandboxes = mgr
    res = run_engine(h.inputs, h.deps)
    argv = _argv(mgr, "run_tools.py")
    assert _flag(argv, "--manifest") == ["poetry.lock"] and "poetry.lock" not in _flag(
        argv, "--changed"
    )
    dep = [c for c in res.additional if c.path == "poetry.lock"]
    assert len(dep) == 1 and dep[0].category == "security" and dep[0].severity == "major"
    assert dep[0].source == "tool:trivy" and "CVE-2024-0001" in dep[0].title
    assert dep[0] in res.candidates and dep[0] not in res.inline


def test_tools_get_a_global_deadline_and_the_effective_base(
    tmp_path: Path, settings: Settings
) -> None:
    h = harness(tmp_path, settings)
    mgr = FakeSandboxManager()
    h.deps.sandboxes = mgr
    res = run_engine(h.inputs, h.deps)
    argv = _argv(mgr, "run_tools.py")
    assert _flag(argv, "--deadline") == [str(settings.sandbox_tools_timeout_s - 30)]
    assert _flag(argv, "--base") == [h.inputs.base_sha] and res.base_sha == h.inputs.base_sha


def test_incremental_fallback_uses_the_pr_base(tmp_path: Path, settings: Settings) -> None:
    tdir = write_stub_tools(tmp_path / "tools")
    log = tmp_path / "argv.json"
    (tdir / "run_tools.py").write_text(
        "import json, sys\n"
        f"open({str(log)!r}, 'w').write(json.dumps(sys.argv))\n"
        "print(json.dumps({'version': 1, 'runs': [], 'findings': []}))\n"
    )
    h = harness(tmp_path, settings, tools_dir=tdir, incremental=True, base_sha="d" * 40)
    res = run_engine(h.inputs, h.deps)
    assert res.incremental is False and res.base_sha == h.inputs.pr.base_sha
    assert _flag(json.loads(log.read_text()), "--base") == [h.inputs.pr.base_sha]
    from decimal import Decimal

    from app.review.posting import make_details

    assert make_details(res, h.inputs, Decimal("1")).base_sha == h.inputs.pr.base_sha


def test_tools_cache_key_covers_base_and_tool_options(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings)
    cache = DictCache()
    h.deps.cache = cache
    run_engine(h.inputs, h.deps)
    level9 = HootPRConfig.model_validate({"reviews": {"tools": {"phpstan": {"level": 9}}}})
    semgrep = HootPRConfig.model_validate(
        {"reviews": {"tools": {"semgrep": {"config_file": "rules.yml"}}}}
    )
    for variant in (
        {"config": level9},
        {"config": semgrep},
        {"base_sha": "e" * 40},
    ):
        h.sink.stages.clear()
        run_engine(EngineInputs(**{**h.inputs.__dict__, **variant}), h.deps)
        tools = next(s for s in h.sink.stages if s.name == "tools")
        assert tools.detail is not None and "(cached)" not in tools.detail, variant
    assert len([k for k in cache.data if k[1] == "tools"]) == 4


def test_incremental_summary_describes_the_whole_pr(tmp_path: Path, settings: Settings) -> None:
    """Only the new commits are reviewed; the walkthrough/description still cover every file."""
    base = {**BASE, "app/other.py": "a = 1\n"}
    head = {**HEAD, "app/other.py": "a = 2\n"}
    h = harness(tmp_path, settings, base=base, head=head, incremental=True)
    platform = h.deps.platform
    full = platform.get_diff(REF, 7)

    class IncrementalPlatform(type(platform)):  # type: ignore[misc]
        def get_diff(
            self, repo: Any, number: int, base_sha: Any = None, head_sha: Any = None
        ) -> Any:
            if base_sha:
                return [f for f in full if f.path == "app/db.py"]
            return list(full)

    platform.__class__ = IncrementalPlatform
    res = run_engine(h.inputs, h.deps)
    assert res.incremental is True and res.reviewed_files == ["app/db.py"]
    summary_req = next(
        r for r in reversed(h.fake.requests) if "WalkthroughSummary" in json.dumps(r["body"])
    )
    user = summary_req["body"]["messages"][1]["content"]
    assert "### FILE app/other.py" in user and "### FILE app/db.py" in user
    assert {p for g in res.summary.changes for p in g.files} == {"app/db.py", "app/other.py"}


def test_review_findings_are_capped_before_the_judge(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings)
    h.deps.settings = settings.model_copy(update={"review_max_comments": 2})
    h.fake.findings = [{**SQLI, "title": f"f{i}", "confidence": 0.5 + i / 100} for i in range(8)]
    res = run_engine(h.inputs, h.deps)
    capped = [c for c in res.candidates if c.reason == "finding_budget_exhausted"]
    assert len(capped) == 2 and res.degraded["findings_capped"] == 2
    assert {c.title for c in capped} == {"f0", "f1"}  # lowest confidence dropped first


def test_review_token_budget_skips_remaining_tasks(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings)
    h.deps.settings = settings.model_copy(update={"review_max_input_tokens": 1000})
    h.fake.prompt_tokens = 5000
    res = run_engine(h.inputs, h.deps)
    assert res.degraded["token_budget"] == [0]
    assert [t["status"] for t in h.sink.tasks.values()] == ["skipped"]


def test_credit_budget_skips_remaining_tasks_and_meters_by_stage(
    tmp_path: Path, settings: Settings
) -> None:
    from decimal import Decimal

    h = harness(tmp_path, settings, credit_budget=Decimal("0.10"))
    h.fake.prompt_tokens = 5000  # triage + plan alone pass 85% of the 0.10 budget
    res = run_engine(h.inputs, h.deps)
    assert res.degraded["credit_budget"] == "reached"
    assert [t["status"] for t in h.sink.tasks.values()] == ["skipped"]
    assert {"triage", "plan", "summarize"} <= set(res.credits_by_stage)
    assert "agents" not in res.credits_by_stage
    assert res.credits == sum(res.credits_by_stage.values()) and res.credits > 0


def test_agent_shell_can_be_disabled(tmp_path: Path, settings: Settings) -> None:
    h = harness(tmp_path, settings)
    h.deps.agent_shell = False
    run_engine(h.inputs, h.deps)
    agent_req = next(r for r in h.fake.requests if r["body"].get("tools"))
    assert "shell" not in {t["function"]["name"] for t in agent_req["body"]["tools"]}


def test_graph_parse_memory_at_the_output_cap() -> None:
    """Spec §11.3: the 256 MB worker parses a graph at GRAPH_MAX_OUTPUT_KB without a big peak."""
    import gc
    import tracemalloc

    from app.review.engine import GRAPH_MAX_OUTPUT_KB
    from app.review.graph import CodeGraph

    n = 20_000
    ids = [
        f"src/services/m{i // 50:04d}/handlers_{i % 50:03d}.py#Service.method_{i}@{i}"
        for i in range(n)
    ]
    sig = "def method(self, request: Request, user_id: int) -> Response"
    syms = [
        {"id": ids[i], "kind": "method", "name": f"method_{i}",
         "qualified_name": f"Service.method_{i}", "path": ids[i].split("#")[0],
         "start_line": 1, "end_line": 20, "signature": sig}
        for i in range(n)
    ]  # fmt: skip
    edges = [
        {"from": ids[i % n], "to": ids[(i * 7 + 3) % n], "kind": "calls"} for i in range(3 * n)
    ]
    doc = {"version": 1, "scope": "full", "truncated": False, "files": [], "symbols": syms,
           "edges": edges, "errors": []}  # fmt: skip
    raw = json.dumps(doc, separators=(",", ":"))
    del doc
    del syms, edges, ids
    gc.collect()
    assert len(raw) <= GRAPH_MAX_OUTPUT_KB * 1024  # a max-size graph fits under the cap
    tracemalloc.start()
    try:
        data = json.loads(raw)
        g = CodeGraph.from_json(data)
        del data
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(g) == n and sys.getsizeof(raw) < 17 * 1024 * 1024
    assert peak < 90 * 1024 * 1024, peak / 2**20
    assert retained < 35 * 1024 * 1024, retained / 2**20
