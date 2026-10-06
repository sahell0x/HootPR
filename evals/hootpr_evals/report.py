"""Eval reports: evals/reports/<date>-<model>.md + .json, and the README's latest table (spec §14)."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from hootpr_evals.metrics import CaseResult, Metrics

if TYPE_CHECKING:
    from hootpr_evals.learnings import LearningCaseResult, LearningMetrics

LATEST = ("<!-- hootpr:eval-latest:start -->", "<!-- hootpr:eval-latest:end -->")
HISTORY = ("<!-- hootpr:eval-history:start -->", "<!-- hootpr:eval-history:end -->")
LEARNINGS = ("<!-- learnings:start -->", "<!-- learnings:end -->")


@dataclass
class RunReport:
    name: str  # "default" or an ablation name (judge_off, tools_off, steps_N, ...)
    metrics: Metrics
    results: list[CaseResult]


@dataclass
class EvalReport:
    date: str
    review_model: str
    cheap_model: str
    review_host: str
    cheap_host: str
    fake_llm: bool
    sandbox: str
    runs: list[RunReport]  # runs[0] is the main run
    notes: list[str]


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _usd(v: Decimal | None) -> str:
    return "n/a" if v is None else f"${v:.4f}"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _basename(day: str, model: str, fake: bool) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") or "model"
    return f"{day}-{slug}" + ("-fake" if fake else "")


def report_basename(r: EvalReport) -> str:
    return _basename(r.date, r.review_model, r.fake_llm)


HEADER = (
    "| Run | Precision | Recall | F1 | Clean-PR FP rate | Comments/PR | Tokens in/out per PR | "
    "Cost/PR | Latency p50 | Errors |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
)


def _summary_row(label: str, m: Metrics) -> str:
    return (
        f"| {_cell(label)} | {_pct(m.precision)} | {_pct(m.recall)} | {_pct(m.f1)} | {_pct(m.clean_fp_rate)} | "
        f"{m.comments_per_pr:.1f} | {m.tokens_in_per_pr:.0f} / {m.tokens_out_per_pr:.0f} | "
        f"{_usd(m.cost_per_pr)} | {m.latency_p50_s:.1f}s | {m.errors}/{m.cases} |"
    )


def render_markdown(r: EvalReport) -> str:
    main = r.runs[0]
    mode = "fake LLM (oracle; pipeline check, not a quality number)" if r.fake_llm else "real LLM"
    out = [
        f"# HootPR eval — {r.review_model} / {r.cheap_model} ({r.date})",
        "",
        f"- Mode: {mode}",
        f"- Providers: review `{r.review_host}`, cheap `{r.cheap_host}`",
        f"- Sandbox: {r.sandbox}",
        f"- Cases: {main.metrics.cases}",
        *(f"- Note: {n}" for n in r.notes),
        "",
        "## Summary",
        "",
        HEADER,
        _summary_row(main.name, main.metrics),
        "",
        "## Per category",
        "",
        "| Category | Precision | Recall | TP | FP | FN |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    out += [
        f"| {c} | {_pct(v.precision)} | {_pct(v.recall)} | {v.tp} | {v.fp} | {v.fn} |"
        for c, v in main.metrics.per_category.items()
    ]
    out += [
        "",
        "## Per case",
        "",
        "| Case | Lang | Kind | Expected | Found | TP | FP | Missed | Cost | Latency | Error |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for c in main.results:
        out.append(
            f"| {c.case_id} | {c.language} | {c.kind} | {len(c.expected)} | {len(c.findings)} | "
            f"{len(c.match.matched)} | {len(c.match.false_positives)} | {len(c.match.missed)} | "
            f"{_usd(c.cost_usd)} | {c.latency_s:.1f}s | {_cell(c.error or '')} |"
        )
    if len(r.runs) > 1:
        out += ["", "## Ablations", "", HEADER, *(_summary_row(run.name, run.metrics) for run in r.runs)]
    return "\n".join(out) + "\n"


def _jsonable(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: _jsonable(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    return o


def to_json(r: EvalReport) -> dict[str, Any]:
    body: dict[str, Any] = _jsonable(r)
    return {"version": 1, **body}


def write_report(r: EvalReport, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    base = reports_dir / report_basename(r)
    # not with_suffix: a model name like gpt-4.1 would lose its ".1"
    md, js = base.with_name(base.name + ".md"), base.with_name(base.name + ".json")
    md.write_text(render_markdown(r))
    js.write_text(json.dumps(to_json(r), indent=2, default=str) + "\n")
    return md, js


def _block(text: str, markers: tuple[str, str]) -> tuple[int, int] | None:
    i, j = text.find(markers[0]), text.find(markers[1])
    return (i, j) if i != -1 and j > i else None


def _replace(text: str, markers: tuple[str, str], body: str) -> str:
    span = _block(text, markers)
    if span is None:
        return f"{text.rstrip()}\n\n{markers[0]}\n{body}\n{markers[1]}\n"
    i, j = span
    return text[: i + len(markers[0])] + "\n" + body + "\n" + text[j:]


def update_readme(readme: Path, r: EvalReport, md_path: Path) -> None:
    """Replace the "latest" block and prepend one line to the history block (idempotent per report)."""
    text = readme.read_text() if readme.exists() else "# HootPR evals\n"
    rel = f"reports/{md_path.name}"
    m = r.runs[0].metrics
    latest = "\n".join(
        [
            f"Latest: [{md_path.name}]({rel})" + (" — fake LLM pipeline check" if r.fake_llm else ""),
            "",
            "| Review model | Cheap model | Precision | Recall | F1 | Clean-PR FP rate | Cost/PR |",
            "|---|---|---:|---:|---:|---:|---:|",
            f"| {_cell(r.review_model)} | {_cell(r.cheap_model)} | {_pct(m.precision)} | {_pct(m.recall)} | "
            f"{_pct(m.f1)} | {_pct(m.clean_fp_rate)} | {_usd(m.cost_per_pr)} |",
        ]
    )
    text = _replace(text, LATEST, latest)
    span = _block(text, HISTORY)
    history = text[span[0] + len(HISTORY[0]) : span[1]].strip().splitlines() if span else []
    line = f"- [{md_path.name}]({rel}): P {_pct(m.precision)}, R {_pct(m.recall)}, F1 {_pct(m.f1)}"
    history = [line, *[h for h in history if h.strip() and f"({rel})" not in h]]
    readme.write_text(_replace(text, HISTORY, "\n".join(history)))


# --- learnings suite (phase-3 E2) -------------------------------------------------------------------
# `meta` keys: date, model (review model), fake_llm ("yes"/"no"), plus anything else worth printing
# (cheap_model, embed_model, sandbox, min_similarity, note, ...).


def _is_fake(meta: dict[str, str]) -> bool:
    return meta.get("fake_llm", "no").lower() in ("yes", "true", "1")


def learnings_basename(meta: dict[str, str]) -> str:
    return _basename(meta.get("date", "undated"), meta.get("model", "model"), _is_fake(meta)) + "-learnings"


def _learnings_summary(m: LearningMetrics) -> list[str]:
    return [
        "| Metric | Value |",
        "|---|---:|",
        f"| Suppression rate | {_pct(m.suppression_rate)} |",
        f"| Adoption rate | {_pct(m.adoption_rate)} |",
        f"| Retention | {_pct(m.retention)} |",
        f"| Retrieval hit rate | {_pct(m.retrieval_hit_rate)} |",
        f"| Findings delta | {m.findings_delta:+d} |" if m.findings_delta else "| Findings delta | 0 |",
        f"| Errors | {m.errors}/{m.cases} |",
    ]


def render_learnings_markdown(
    metrics: LearningMetrics, results: Sequence[LearningCaseResult], meta: dict[str, str]
) -> str:
    mode = "fake LLM (oracle; pipeline check, not a quality number)" if _is_fake(meta) else "real LLM"
    extra = [f"- {k.replace('_', ' ').capitalize()}: {_cell(v)}" for k, v in meta.items()
             if k not in ("date", "model", "fake_llm", "note")]  # fmt: skip
    out = [
        f"# HootPR learnings eval — {meta.get('model', 'model')} ({meta.get('date', 'undated')})",
        "",
        f"- Mode: {mode}",
        *extra,
        f"- Cases: {metrics.cases}",
        *([f"- Note: {_cell(meta['note'])}"] if meta.get("note") else []),
        "",
        "## Summary",
        "",
        *_learnings_summary(metrics),
        "",
        "## Per case",
        "",
        "| Case | Findings without | With | Learnings used | Error |",
        "|---|---:|---:|---:|---|",
    ]
    for r in results:
        err = r.baseline.error or r.with_learnings.error or ""
        out.append(
            f"| {r.case_id} | {len(r.baseline.findings)} | {len(r.with_learnings.findings)} | "
            f"{r.learnings_used}/{r.learnings_total} | {_cell(err)} |"
        )
    return "\n".join(out) + "\n"


def learnings_to_json(
    metrics: LearningMetrics, results: Sequence[LearningCaseResult], meta: dict[str, str]
) -> dict[str, Any]:
    return {
        "version": 1,
        "suite": "learnings",
        "meta": dict(meta),
        "metrics": _jsonable(metrics),
        "cases": [_jsonable(r) for r in results],
    }


def write_learnings_report(
    metrics: LearningMetrics, results: Sequence[LearningCaseResult], meta: dict[str, str], reports_dir: Path
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    base = reports_dir / learnings_basename(meta)
    md, js = base.with_name(base.name + ".md"), base.with_name(base.name + ".json")
    md.write_text(render_learnings_markdown(metrics, results, meta))
    js.write_text(json.dumps(learnings_to_json(metrics, results, meta), indent=2, default=str) + "\n")
    return md, js


def update_learnings_readme(readme: Path, metrics: LearningMetrics, md_path: Path, meta: dict[str, str]) -> None:
    """Replace the README's learnings block with the latest learnings run (idempotent)."""
    text = readme.read_text() if readme.exists() else "# HootPR evals\n"
    rel = f"reports/{md_path.name}"
    body = "\n".join(
        [
            f"Latest: [{md_path.name}]({rel})" + (" — fake LLM pipeline check" if _is_fake(meta) else ""),
            "",
            *_learnings_summary(metrics),
        ]
    )
    readme.write_text(_replace(text, LEARNINGS, body))
