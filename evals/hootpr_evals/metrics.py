"""Precision / recall / F1 overall and per category, clean-PR false positives, cost, latency (spec §14)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from hootpr_evals.case import ExpectedIssue
from hootpr_evals.matching import CaseMatch, ReviewFinding


@dataclass
class CaseResult:
    case_id: str
    language: str
    kind: str
    expected: list[ExpectedIssue]
    findings: list[ReviewFinding]
    match: CaseMatch
    inline_count: int
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    latency_s: float
    llm_calls: int
    error: str | None = None
    learnings_used: int = 0  # distinct learnings the engine injected (EngineResult.learnings_used)


@dataclass
class CategoryMetrics:
    precision: float | None
    recall: float | None
    tp: int
    fp: int
    fn: int


@dataclass
class Metrics:
    precision: float | None
    recall: float | None
    f1: float | None
    tp: int
    fp: int
    fn: int
    per_category: dict[str, CategoryMetrics] = field(default_factory=dict)
    clean_fp_rate: float | None = None  # share of clean PRs with at least one finding
    clean_findings_mean: float | None = None  # findings per clean PR
    comments_per_pr: float = 0.0
    tokens_in_per_pr: float = 0.0
    tokens_out_per_pr: float = 0.0
    cost_per_pr: Decimal | None = None
    latency_mean_s: float = 0.0
    latency_p50_s: float = 0.0
    cases: int = 0
    errors: int = 0


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return 0.0 if p == 0 or r == 0 else None
    return 2 * p * r / (p + r) if p + r else 0.0


def compute_metrics(results: Sequence[CaseResult]) -> Metrics:
    tp = sum(len(r.match.matched) for r in results)
    fp = sum(len(r.match.false_positives) for r in results)
    fn = sum(len(r.match.missed) for r in results)
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    cats: dict[str, dict[str, int]] = {}

    def bump(cat: str, key: str) -> None:
        cats.setdefault(cat, {"tp": 0, "fp": 0, "fn": 0, "found": 0, "expected": 0})[key] += 1

    # Recall is attributed to the expected issue's category, precision to the finding's category.
    for r in results:
        by_id = {i.id: i for i in r.expected}
        for fi, iid in r.match.matched:
            bump(by_id[iid].category, "tp")
            bump(by_id[iid].category, "expected")
            bump(r.findings[fi].category, "found")
        for fi in r.match.false_positives:
            bump(r.findings[fi].category, "fp")
            bump(r.findings[fi].category, "found")
        for iid in r.match.missed:
            if iid in by_id:
                bump(by_id[iid].category, "fn")
                bump(by_id[iid].category, "expected")
    per_category = {
        c: CategoryMetrics(
            _ratio(v["found"] - v["fp"], v["found"]), _ratio(v["tp"], v["expected"]), v["tp"], v["fp"], v["fn"]
        )
        for c, v in sorted(cats.items())
    }
    clean = [r for r in results if r.kind == "clean"]
    n = len(results) or 1
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    latencies = [r.latency_s for r in results] or [0.0]
    return Metrics(
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        tp=tp,
        fp=fp,
        fn=fn,
        per_category=per_category,
        clean_fp_rate=_ratio(sum(1 for r in clean if r.findings), len(clean)),
        clean_findings_mean=(sum(len(r.findings) for r in clean) / len(clean)) if clean else None,
        comments_per_pr=sum(r.inline_count for r in results) / n,
        tokens_in_per_pr=sum(r.input_tokens for r in results) / n,
        tokens_out_per_pr=sum(r.output_tokens for r in results) / n,
        cost_per_pr=(sum(costs, Decimal(0)) / len(costs)) if costs else None,
        latency_mean_s=statistics.fmean(latencies),
        latency_p50_s=statistics.median(latencies),
        cases=len(results),
        errors=sum(1 for r in results if r.error),
    )
