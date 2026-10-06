"""Runs the real review engine (contract C2) on eval cases with LocalPlatform: nothing is posted anywhere.

The engine is called through `ENGINE` (default: `run_production_engine`), a module-level hook so the
runner/CLI can be exercised against a stand-in engine in tests; backend engine modules are imported
lazily inside `run_production_engine`."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from app.kv import MemoryKV
from app.llm.gateway import LLMGateway
from app.llm.metering import InMemoryRecorder
from app.llm.types import role_configs
from app.settings import Settings

from hootpr_evals.case import Case, Materialized, materialize
from hootpr_evals.matching import LLMMatcher, LocationMatcher, Matcher, ReviewFinding, match_case
from hootpr_evals.metrics import CaseResult
from hootpr_evals.oracle_llm import OracleLLM

# name -> app.review.engine.Ablation kwargs (spec §14 ablations)
ABLATIONS: dict[str, dict[str, Any]] = {
    "default": {},
    "judge_off": {"judge": False},
    "tools_off": {"tools": False},
    "steps_0": {"agent_max_steps": 0},
    "steps_4": {"agent_max_steps": 4},
    "steps_8": {"agent_max_steps": 8},
}
LLMFactory = Callable[[Case, InMemoryRecorder], Any]
KnowledgeFactory = Callable[[Any], Any]  # LLMGateway -> KnowledgeBase
MatcherFactory = Callable[[Case], Matcher]
DOCKER_CLIENT_TIMEOUT_S = 60


class CandidateLike(Protocol):
    """The `app.review.findings.Candidate` fields the evals read (contract C2)."""

    @property
    def path(self) -> str: ...
    @property
    def start_line(self) -> int | None: ...
    @property
    def end_line(self) -> int: ...
    @property
    def severity(self) -> str: ...
    @property
    def category(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def body(self) -> str: ...
    @property
    def confidence(self) -> float: ...


class EngineOutcome(Protocol):
    @property
    def inline(self) -> Sequence[CandidateLike]: ...
    @property
    def additional(self) -> Sequence[CandidateLike]: ...


@dataclass(frozen=True)
class EngineCall:
    case: Case
    mat: Materialized
    settings: Settings
    sandbox: str  # "local" | "docker"
    ablation: dict[str, Any]
    llm: Any  # LLMGateway
    workdir: Path
    knowledge: Any = None  # app.knowledge.base.KnowledgeBase (contract C2); None = engine default


EngineFn = Callable[[EngineCall], EngineOutcome]


@dataclass(frozen=True)
class RunOptions:
    settings: Settings
    sandbox: str = "local"
    ablation_name: str = "default"
    llm_match: bool = True


def real_llm_factory(settings: Settings) -> LLMFactory:
    return lambda case, rec: LLMGateway(role_configs(settings), rec, MemoryKV(), log_full=False)


def oracle_llm_factory(settings: Settings, noise: bool = False) -> LLMFactory:
    def make(case: Case, rec: InMemoryRecorder) -> LLMGateway:
        oracle = OracleLLM(case.issues, noise=noise)
        return LLMGateway(
            role_configs(settings), rec, MemoryKV(), client_factory=lambda cfg: oracle.client(), sleep=lambda s: None
        )

    return make


def real_matcher_factory(settings: Settings, llm_match: bool = True) -> MatcherFactory:
    if not llm_match:
        return lambda case: LocationMatcher()
    return lambda case: LLMMatcher(LLMGateway(role_configs(settings), InMemoryRecorder(), MemoryKV()))


def oracle_matcher_factory() -> MatcherFactory:
    return lambda case: LocationMatcher()


class SandboxChoiceError(ValueError):
    pass


LOCAL_NOTE = (
    "local sandbox: repository commands run on this host, so the agent's `shell` tool was disabled "
    "and most static tools were unavailable (run `make sandbox-image` for full fidelity)"
)


def choose_sandbox(settings: Settings, wanted: str, *, fake_llm: bool = True) -> tuple[str, str | None]:
    """`auto` picks docker when the sandbox image exists locally. It falls back to the local (host)
    sandbox only for fake-LLM pipeline checks: a real model steered by untrusted eval repos must
    never pick commands on the developer's machine unless `--sandbox local` is passed explicitly
    (and even then the agent gets no `shell` tool)."""
    if wanted == "docker":
        return "docker", None
    if wanted == "local":
        return "local", LOCAL_NOTE
    try:
        import docker

        docker.from_env(timeout=10).images.get(settings.sandbox_image)
        return "docker", None
    except Exception:
        if not fake_llm:
            raise SandboxChoiceError(
                f"sandbox image {settings.sandbox_image} not available: run `make sandbox-image`, or pass "
                "--sandbox local to run on this host without the agent shell tool"
            ) from None
        return "local", LOCAL_NOTE


def _sandboxes(kind: str, settings: Settings, workdir: Path) -> Any:
    if kind == "docker":
        import docker
        from app.sandbox.docker import DockerSandboxManager

        # Evals run on the host: talk to the local daemon (not the compose docker-proxy). The socket
        # timeout must outlive the longest exec, as in DockerSandboxManager.from_settings.
        timeout = max(settings.sandbox_tools_timeout_s, settings.sandbox_graph_timeout_s) + DOCKER_CLIENT_TIMEOUT_S
        return DockerSandboxManager(
            lambda: docker.from_env(timeout=timeout), image=settings.sandbox_image, network=settings.sandbox_network
        )
    from app.sandbox.local import LocalSandboxManager

    return LocalSandboxManager(base_dir=workdir)


def run_production_engine(call: EngineCall) -> EngineOutcome:
    """Contract C2: one full, non-incremental review of the case PR on LocalPlatform."""
    from app.config.schema import HootPRConfig
    from app.platforms.base import PullRequest, RepoRef
    from app.platforms.local import LocalPlatform
    from app.review.engine import (  # type: ignore[import-not-found,unused-ignore]
        Ablation,
        EngineDeps,
        EngineInputs,
        run_engine,
    )
    from app.review.trace import InMemoryTraceSink  # type: ignore[import-not-found,unused-ignore]
    from uuid_utils.compat import uuid7

    case, mat = call.case, call.mat
    ref = RepoRef("github", f"eval-{case.id}", f"evals/{case.id}")
    platform = LocalPlatform()
    pr = PullRequest(
        1, case.meta.title, case.meta.description, "eval-author", "open", False, "main", "eval",
        mat.base_sha, mat.head_sha, (), "",
    )  # fmt: skip
    platform.add_pull_request(ref, pr, mat.files)
    platform.register_repo_path(ref, mat.path)
    deps = EngineDeps(
        platform=platform,
        sandboxes=_sandboxes(call.sandbox, call.settings, call.workdir),
        llm=call.llm,
        trace=InMemoryTraceSink(),
        settings=call.settings,
        ablation=Ablation(**call.ablation),
        # The local sandbox is the developer's host: no arbitrary agent commands there.
        agent_shell=call.sandbox == "docker",
        # Contract C2 (phase 3): only passed when set, so reviews without learnings use the default.
        **({"knowledge": call.knowledge} if call.knowledge is not None else {}),
    )
    inputs = EngineInputs(
        review_id=uuid7(),
        org_id=None,
        repo=ref,
        pr=pr,
        base_sha=mat.base_sha,
        head_sha=mat.head_sha,
        incremental=False,
        config=HootPRConfig.model_validate(case.meta.config),
        config_source="eval",
    )
    result: EngineOutcome = run_engine(inputs, deps)
    return result


ENGINE: EngineFn = run_production_engine


def run_case(
    case: Case,
    opts: RunOptions,
    llm_factory: LLMFactory,
    matcher_factory: MatcherFactory,
    workdir: Path,
    knowledge_factory: KnowledgeFactory | None = None,
) -> CaseResult:
    """Review one case. `knowledge_factory` (learnings suite) builds the engine's knowledge base from
    the case's LLM gateway, so embedding calls are metered with the review."""
    workdir.mkdir(parents=True, exist_ok=True)
    rec = InMemoryRecorder()
    findings: list[ReviewFinding] = []
    inline, used, error = 0, 0, None
    started = time.perf_counter()
    try:
        mat = materialize(case, workdir)
        llm = llm_factory(case, rec)
        knowledge = knowledge_factory(llm) if knowledge_factory is not None else None
        call = EngineCall(case, mat, opts.settings, opts.sandbox, ABLATIONS[opts.ablation_name],
                          llm, workdir, knowledge)  # fmt: skip
        result = ENGINE(call)
        findings = [
            ReviewFinding(c.path, c.start_line, c.end_line, c.category, c.severity, c.title, c.body, c.confidence)
            for c in [*result.inline, *result.additional]
        ]
        inline = len(result.inline)
        used = len(getattr(result, "learnings_used", None) or [])
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
    latency = time.perf_counter() - started
    match = match_case(findings, case.issues, matcher_factory(case))
    ok = [r for r in rec.records if r.status == "ok"]
    costs = [r.cost_usd for r in ok if r.cost_usd is not None]
    return CaseResult(
        case_id=case.id,
        language=case.meta.language,
        kind=case.meta.kind,
        expected=list(case.issues),
        findings=findings,
        match=match,
        inline_count=inline,
        input_tokens=sum(r.usage.input_tokens for r in ok),
        cached_tokens=sum(r.usage.cached_tokens for r in ok),
        output_tokens=sum(r.usage.output_tokens for r in ok),
        cost_usd=sum(costs, Decimal(0)) if costs else None,
        latency_s=latency,
        llm_calls=len(rec.records),
        error=error,
        learnings_used=used,
    )


def run_suite(
    cases: Sequence[Case],
    opts: RunOptions,
    llm_factory: LLMFactory,
    matcher_factory: MatcherFactory,
    workdir: Path,
    progress: Callable[[str], None] = print,
) -> list[CaseResult]:
    out: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        progress(f"[{opts.ablation_name}] {i}/{len(cases)} {case.id}")
        out.append(run_case(case, opts, llm_factory, matcher_factory, workdir / opts.ablation_name))
    return out
