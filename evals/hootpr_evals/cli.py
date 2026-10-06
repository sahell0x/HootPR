"""`make eval` CLI (spec §14)."""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from app.settings import Settings
from pydantic import ValidationError

from hootpr_evals.case import DATASETS, LEARNING_DATASETS, Case, load_cases, load_learning_cases
from hootpr_evals.learnings import (
    hash_embed_factory,
    learning_metrics,
    real_embed_factory,
    run_learning_case,
)
from hootpr_evals.metrics import compute_metrics
from hootpr_evals.report import (
    EvalReport,
    RunReport,
    update_learnings_readme,
    update_readme,
    write_learnings_report,
    write_report,
)
from hootpr_evals.runner import (
    ABLATIONS,
    LLMFactory,
    MatcherFactory,
    RunOptions,
    SandboxChoiceError,
    choose_sandbox,
    oracle_llm_factory,
    oracle_matcher_factory,
    real_llm_factory,
    real_matcher_factory,
    run_suite,
)

EVALS = Path(__file__).resolve().parents[1]
ROOT = EVALS.parent


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def _host(url: str) -> str:
    return urlparse(url).hostname or url


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="make eval", description="HootPR review-quality eval suite (spec §14)")
    ap.add_argument(
        "--suite",
        choices=("review", "learnings"),
        default="review",
        help="review: review-quality suite; learnings: does a taught learning change the next review",
    )
    ap.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--fake-llm", action="store_true", help="oracle fake LLM: pipeline check, no keys needed")
    ap.add_argument("--noise", action="store_true", help="fake LLM also emits low-confidence noise")
    ap.add_argument("--sandbox", choices=("auto", "local", "docker"), default="auto")
    ap.add_argument(
        "--ablations", default="", help=f"comma-separated: {', '.join(a for a in ABLATIONS if a != 'default')}"
    )
    ap.add_argument("--no-llm-match", action="store_true", help="match on path + lines only")
    ap.add_argument("--datasets", type=Path, default=None, help="default: datasets/cases or datasets/learning_cases")
    ap.add_argument("--reports-dir", type=Path, default=EVALS / "reports")
    ap.add_argument("--readme", type=Path, default=EVALS / "README.md")
    ap.add_argument("--no-readme", action="store_true", help="do not update the README tables")
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    try:
        settings = Settings(_env_file=str(a.env_file) if a.env_file.exists() else None)
        only = [c for c in a.cases.split(",") if c] or None
        if a.suite == "learnings":
            cases = load_learning_cases(a.datasets or LEARNING_DATASETS, only)
        else:
            cases = load_cases(a.datasets or DATASETS, only)
    except (ValueError, ValidationError, OSError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    ablations = [x for x in a.ablations.split(",") if x] if a.suite == "review" else []
    unknown = [x for x in ablations if x not in ABLATIONS]
    if unknown:
        print(f"configuration error: unknown ablation(s) {unknown}; known: {sorted(ABLATIONS)}", file=sys.stderr)
        return 2
    if not cases:
        print(f"configuration error: no cases under {a.datasets or DATASETS}", file=sys.stderr)
        return 2
    if a.suite == "learnings" and not a.fake_llm and not settings.llm_embed_api_key.get_secret_value():
        print("configuration error: the learnings suite needs LLM_EMBED_API_KEY in .env, or pass --fake-llm",
              file=sys.stderr)  # fmt: skip
        return 2
    if not a.fake_llm and not (
        settings.llm_review_api_key.get_secret_value() and settings.llm_cheap_api_key.get_secret_value()
    ):
        print(
            "configuration error: set LLM_REVIEW_API_KEY and LLM_CHEAP_API_KEY in .env, or pass --fake-llm",
            file=sys.stderr,
        )
        return 2
    try:
        kind, note = choose_sandbox(settings, a.sandbox, fake_llm=a.fake_llm)
    except SandboxChoiceError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    llm = oracle_llm_factory(settings, noise=a.noise) if a.fake_llm else real_llm_factory(settings)
    matcher = oracle_matcher_factory() if a.fake_llm else real_matcher_factory(settings, not a.no_llm_match)
    if a.suite == "learnings":
        return _run_learnings(a, settings, cases, kind, note, llm, matcher)
    runs: list[RunReport] = []
    with tempfile.TemporaryDirectory(prefix="hootpr-evals-") as tmp:
        for name in dict.fromkeys(["default", *ablations]):
            opts = RunOptions(settings, sandbox=kind, ablation_name=name, llm_match=not a.no_llm_match)
            results = run_suite(cases, opts, llm, matcher, Path(tmp))
            runs.append(RunReport(name, compute_metrics(results), results))
    notes = [note] if note else []
    if a.fake_llm:
        notes.append("fake LLM: scores are ~100% by construction; this run only verifies the pipeline")
    report = EvalReport(
        date.today().isoformat(),
        settings.llm_review_model,
        settings.llm_cheap_model,
        _host(settings.llm_review_base_url),
        _host(settings.llm_cheap_base_url),
        a.fake_llm,
        kind,
        runs,
        notes,
    )
    md, _ = write_report(report, a.reports_dir)
    if not a.no_readme:
        update_readme(a.readme, report, md)
    m = runs[0].metrics
    print(f"precision {_fmt(m.precision)} recall {_fmt(m.recall)} f1 {_fmt(m.f1)} errors {m.errors}/{m.cases}")
    print(f"report: {md}")
    for r in runs[0].results:
        if r.error:
            print(f"  {r.case_id}: {r.error}", file=sys.stderr)
    return 1 if m.cases and m.errors == m.cases else 0


def _run_learnings(
    a: argparse.Namespace,
    settings: Settings,
    cases: list[Case],
    kind: str,
    note: str | None,
    llm: LLMFactory,
    matcher: MatcherFactory,
) -> int:
    """`--suite learnings`: two passes per case (without / with the case's learnings); ablations ignored."""
    if a.ablations:
        print("note: --ablations is ignored by --suite learnings", file=sys.stderr)
    # Fake runs: the hashing embedder's cosine between a short learning and a long task prompt is far
    # below real-model similarities, so retrieval is not thresholded (they check plumbing, not quality).
    min_similarity = 0.0 if a.fake_llm else settings.learnings_min_similarity
    embed = hash_embed_factory() if a.fake_llm else real_embed_factory(settings)
    opts = RunOptions(settings, sandbox=kind, llm_match=not a.no_llm_match)
    results = []
    with tempfile.TemporaryDirectory(prefix="hootpr-evals-learnings-") as tmp:
        for i, case in enumerate(cases, 1):
            print(f"[learnings] {i}/{len(cases)} {case.id}")
            results.append(
                run_learning_case(case, opts, llm, matcher, Path(tmp) / case.id, embed, min_similarity=min_similarity)
            )
    m = learning_metrics(results)
    notes = [n for n in (note, "fake LLM: scores are 100% by construction" if a.fake_llm else None) if n]
    meta = {
        "date": date.today().isoformat(),
        "model": settings.llm_review_model,
        "fake_llm": "yes" if a.fake_llm else "no",
        "cheap_model": settings.llm_cheap_model,
        "embed_model": "hashing (fake)" if a.fake_llm else settings.llm_embed_model,
        "min_similarity": f"{min_similarity:g}",
        "sandbox": kind,
        **({"note": "; ".join(notes)} if notes else {}),
    }
    md, _ = write_learnings_report(m, results, meta, a.reports_dir)
    if not a.no_readme:
        update_learnings_readme(a.readme, m, md, meta)
    print(
        f"suppression {_fmt(m.suppression_rate)} adoption {_fmt(m.adoption_rate)} retention {_fmt(m.retention)} "
        f"retrieval {_fmt(m.retrieval_hit_rate)} delta {m.findings_delta} errors {m.errors}/{m.cases}"
    )
    print(f"report: {md}")
    for r in results:
        for label, res in (("baseline", r.baseline), ("with learnings", r.with_learnings)):
            if res.error:
                print(f"  {r.case_id} ({label}): {res.error}", file=sys.stderr)
    return 1 if m.cases and m.errors == m.cases else 0
