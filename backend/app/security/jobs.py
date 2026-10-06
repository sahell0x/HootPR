"""Repo-level security jobs (spec §10.3): attack surface map + security architecture review.

Always on demand (dashboard button or ``@hootpr security review``): a sandbox clones the default
branch, ``attack_surface.py`` inventories it, and a security review additionally asks the
``review`` model for a prioritized report over the map + key files. The review reserves
``CREDITS_SECURITY_REVIEW`` (ref_type ``security_scan``), commits it with ledger reason
``security_review`` on success and releases it on any HootPR-side failure.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.ledger import InsufficientCredits
from app.billing.pricing import fmt_credits
from app.llm.types import TraceContext
from app.logging import get_logger
from app.models import Organization, PullRequest, Repository, SecurityScan
from app.models.base import utcnow
from app.platforms.base import GitPlatform, RepoRef
from app.platforms.factory import close_platform, repo_ref
from app.review.llm import MeteredLLM
from app.review.safety import clean_prose, repo_host, untrusted
from app.sandbox.base import Sandbox, sandbox_session
from app.security.prompts import SECURITY_REVIEW_SYSTEM
from app.security.schemas import SecurityReport
from app.security.store import REF_TYPE
from app.worker.context import WorkerContext

log = get_logger(__name__)
LEDGER_REASON = "security"
STALE_AFTER = timedelta(minutes=60)
SURFACE_MAX_OUTPUT_KB = 8 * 1024
KEY_FILES_MAX = 15
KEY_FILE_CHARS = 6000
KEY_FILES_TOTAL_CHARS = 60_000
PROMPT_LIST_MAX = 150
REPORT_MAX_RISKS = 12
RISK_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}


class SecurityJobError(Exception):
    """A HootPR-side failure with a message safe to show users."""


def comment_marker(scan_id: UUID) -> str:
    return f"<!-- hootpr:security:{scan_id} -->"


def dashboard_url(ctx: WorkerContext, org: Organization) -> str:
    return f"{ctx.settings.app_base_url.rstrip('/')}/o/{org.slug}/security"


# --- stuck runs -------------------------------------------------------------------------------


def sweep_stuck_scans(ctx: WorkerContext, s: Session, *, now: datetime | None = None) -> int:
    """Fail (and refund) scans a crashed worker left queued/running for over an hour."""
    cutoff = (now or utcnow()) - STALE_AFTER
    rows = (
        s.execute(
            select(SecurityScan).where(
                SecurityScan.status.in_(("queued", "running")),
                SecurityScan.updated_at < cutoff,
            )
        )
        .scalars()
        .all()
    )
    for scan in rows:
        held = ctx.ledger.find_open_reservation(s, REF_TYPE, scan.id)
        if held is not None:
            ctx.ledger.release(s, held)
        scan.status, scan.error, scan.finished_at = "failed", "Timed out.", utcnow()
    s.commit()
    return len(rows)


# --- surface ------------------------------------------------------------------------------


def run_surface(ctx: WorkerContext, sb: Sandbox) -> dict[str, Any]:
    argv = [
        sb.python,
        f"{sb.tools_dir}/attack_surface.py",
        "--repo",
        sb.repo_dir,
        "--max-files",
        str(ctx.settings.graph_max_files),
    ]
    r = sb.exec(
        argv, timeout_s=ctx.settings.sandbox_graph_timeout_s, max_output_kb=SURFACE_MAX_OUTPUT_KB
    )
    if r.timed_out:
        raise SecurityJobError("The attack surface scan timed out.")
    if not r.ok or r.truncated:
        raise SecurityJobError("The attack surface scan failed.")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        raise SecurityJobError("The attack surface scan produced invalid output.") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise SecurityJobError("The attack surface scan produced invalid output.")
    return data


def surface_summary(surface: dict[str, Any]) -> str:
    st = surface.get("stats") or {}
    return (
        f"{st.get('http_endpoints', 0)} HTTP endpoints "
        f"({st.get('unauthenticated_endpoints', 0)} without detected auth), "
        f"{max(0, int(st.get('entry_points', 0)) - int(st.get('http_endpoints', 0)))} other entry "
        f"points, {st.get('outbound_calls', 0)} outbound calls, {st.get('secrets', 0)} secrets "
        f"references, {st.get('iac_findings', 0)} IaC exposure findings"
    )


def _dicts(value: object) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def render_surface_for_prompt(surface: dict[str, Any]) -> str:
    lines = ["Stats: " + json.dumps(surface.get("stats") or {}, sort_keys=True)]
    lines.append("Entry points (kind | name | framework | auth | location | handler):")
    for e in _dicts(surface.get("entry_points"))[:PROMPT_LIST_MAX]:
        auth = f"auth={e.get('auth_evidence') or 'yes'}" if e.get("auth") else "auth=none detected"
        lines.append(
            f"- {e.get('kind')} | {e.get('name')} | {e.get('framework')} | {auth} | "
            f"{e.get('path')}:{e.get('line')} | {e.get('handler', '')}"
        )
    lines.append("Outbound calls:")
    lines += [
        f"- {o.get('callee')} in {o.get('symbol') or '?'} ({o.get('path')}:{o.get('line')})"
        for o in _dicts(surface.get("outbound"))[:50]
    ]
    sinks = surface.get("sinks") or {}
    lines.append("Sensitive sink counts: " + json.dumps(sinks.get("counts") or {}, sort_keys=True))
    for cat, ex in (sinks.get("examples") or {}).items():
        for x in _dicts(ex)[:8]:
            lines.append(f"- {cat}: {x.get('callee')} ({x.get('path')}:{x.get('line')})")
    lines.append("Secrets usage (names only):")
    lines += [
        f"- {x.get('name')} [{x.get('source')}] ({x.get('path')}:{x.get('line')})"
        for x in _dicts(surface.get("secrets"))[:50]
    ]
    lines.append("Infrastructure exposure:")
    lines += [
        f"- {x.get('kind')}/{x.get('rule')}: {x.get('detail')} ({x.get('path')}:{x.get('line')})"
        for x in _dicts(surface.get("iac"))[:50]
    ]
    return "\n".join(lines)


def key_files(surface: dict[str, Any]) -> list[str]:
    """Files worth reading: unauthenticated routes first, then auth code, infra, secrets."""
    ordered: list[str] = []
    eps = _dicts(surface.get("entry_points"))
    ordered += [str(e["path"]) for e in eps if e.get("kind") == "http" and not e.get("auth")]
    ordered += [str(e["path"]) for e in eps if e.get("kind") == "http" and e.get("auth")]
    examples = (surface.get("sinks") or {}).get("examples") or {}
    for cat in ("auth", "crypto", "exec"):
        ordered += [str(x["path"]) for x in _dicts(examples.get(cat))]
    ordered += [str(x["path"]) for x in _dicts(surface.get("iac"))]
    ordered += [str(e["path"]) for e in eps]
    out = [p for p in dict.fromkeys(ordered) if p and not p.startswith(".env")]
    return out[:KEY_FILES_MAX]


def run_review_llm(
    ctx: WorkerContext,
    sb: Sandbox,
    surface: dict[str, Any],
    org_id: UUID,
    repo_name: str,
    scan_id: UUID | None = None,
) -> tuple[SecurityReport, MeteredLLM]:
    parts = [untrusted("attack-surface", render_surface_for_prompt(surface))]
    used = 0
    for path in key_files(surface):
        if used >= KEY_FILES_TOTAL_CHARS:
            break
        try:
            text = sb.read_file(path, max_kb=64)
        except Exception:
            log.warning("security_key_file_unreadable", path=path)
            continue
        text = text[: min(KEY_FILE_CHARS, KEY_FILES_TOTAL_CHARS - used)]
        used += len(text)
        parts.append(f"### FILE {path}\n" + untrusted(f"file:{path}", text))
    llm = MeteredLLM(ctx.llm())
    res = llm.complete(
        "review",
        [
            {"role": "system", "content": SECURITY_REVIEW_SYSTEM},
            {
                "role": "user",
                "content": f"Repository: {repo_name}\n\n" + "\n\n".join(parts),
            },
        ],
        response_model=SecurityReport,
        max_output_tokens=4000,
        # ``task_id`` attributes the calls to the scan (its credit receipt).
        trace=TraceContext(org_id=org_id, task_id=scan_id, stage="security"),
    )
    return cast(SecurityReport, res.parsed), llm


def clean_report(report: SecurityReport, host: str) -> SecurityReport:
    """Every model-written string hardened (it is posted to PRs and shown in the dashboard)."""
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    risks = sorted(report.risks, key=lambda r: order[r.severity])[:REPORT_MAX_RISKS]
    return SecurityReport(
        summary=clean_prose(report.summary, 1200, host),
        overall_risk=report.overall_risk,
        risks=[
            r.model_copy(
                update={
                    "title": clean_prose(" ".join(r.title.split()), 100, host),
                    "category": clean_prose(r.category, 40, host),
                    "description": clean_prose(r.description, 800, host),
                    "affected": [clean_prose(a, 160, host) for a in r.affected[:8]],
                    "recommendation": clean_prose(r.recommendation, 600, host),
                }
            )
            for r in risks
        ],
        strengths=[clean_prose(x, 200, host) for x in report.strengths[:6]],
    )


# --- PR comments ------------------------------------------------------------------------------


def render_report_comment(
    scan: SecurityScan, report: SecurityReport | None, surface: dict[str, Any] | None, url: str
) -> str:
    out = [comment_marker(scan.id)]
    branch = f"`{scan.branch}`" if scan.branch else "the default branch"
    sha = f" at `{scan.commit_sha[:7]}`" if scan.commit_sha else ""
    if report is None:
        out += ["## 🛡️ HootPR security review", "", scan.summary or "No report."]
        return "\n".join([*out, "", f"Details: {url}"])
    icon = RISK_ICON.get(report.overall_risk, "")
    out += [
        "## 🛡️ HootPR security review",
        "",
        f"Security architecture review of {branch}{sha}. "
        f"**Overall risk: {icon} {report.overall_risk}**",
        "",
        report.summary,
        "",
    ]
    if surface:
        out += [f"**Attack surface:** {surface_summary(surface)}.", ""]
    if report.risks:
        out += ["### Prioritized risks", ""]
        for i, r in enumerate(report.risks, 1):
            affected = ", ".join(f"`{a.replace('`', "'")}`" for a in r.affected)
            out += [
                "<details>",
                f"<summary>{i}. {RISK_ICON.get(r.severity, '')} <b>{r.severity}</b> — "
                f"{r.title} ({r.category})</summary>",
                "",
                r.description,
                "",
                *([f"**Affected:** {affected}", ""] if affected else []),
                f"**Recommendation:** {r.recommendation}",
                "",
                "</details>",
            ]
        out.append("")
    if report.strengths:
        out += ["### Strengths", "", *(f"- {x}" for x in report.strengths), ""]
    credits = fmt_credits(scan.credits_charged)
    out += ["---", f"Full report and attack surface map: {url} · Credits charged: {credits}"]
    return "\n".join(out)


def _notify(
    ctx: WorkerContext,
    s: Session,
    platform: GitPlatform | None,
    ref: RepoRef,
    scan: SecurityScan,
    org: Organization,
    report: SecurityReport | None,
    surface: dict[str, Any] | None,
) -> None:
    if platform is None or scan.pr_id is None:
        return
    pr = s.get(PullRequest, scan.pr_id)
    if pr is None:
        return
    try:
        body = render_report_comment(scan, report, surface, dashboard_url(ctx, org))
        platform.upsert_comment(ref, pr.number, comment_marker(scan.id), body)
    except Exception:
        log.warning("security_comment_failed", exc_info=True)


# --- the job --------------------------------------------------------------------------------


def run_security_scan(ctx: WorkerContext, scan_id: UUID) -> None:
    settings = ctx.settings
    with ctx.session_factory() as s:
        sweep_stuck_scans(ctx, s)
        scan = s.get(SecurityScan, scan_id)
        if scan is None or scan.status != "queued":
            return
        repo = s.get(Repository, scan.repo_id)
        org = s.get(Organization, scan.org_id)
        if repo is None or org is None:
            scan.status, scan.error = "failed", "Repository not found."
            s.commit()
            return
        review = scan.kind == "security_review"
        hold = None
        platform: GitPlatform | None = None
        ref = repo_ref(repo)
        if review:
            amount = Decimal(settings.security_min_charge)
            got = ctx.ledger.reserve_up_to(
                s, org.id, settings.security_hold_max, amount, REF_TYPE, scan.id
            )
            if isinstance(got, InsufficientCredits):
                scan.status, scan.finished_at = "no_credits", utcnow()
                scan.summary = (
                    f"Out of credits: a security review needs at least {fmt_credits(amount)} "
                    f"credits to start (balance {fmt_credits(got.balance)})."
                )
                s.commit()
                try:
                    platform = ctx.platforms(s, repo)
                    _notify(ctx, s, platform, ref, scan, org, None, None)
                except Exception:
                    log.warning("security_notify_failed", exc_info=True)
                finally:
                    if platform is not None:
                        close_platform(platform)
                return
            hold = got
        scan.status, scan.started_at = "running", utcnow()
        scan.branch = repo.default_branch or scan.branch or "main"
        s.commit()
        report: SecurityReport | None = None
        metered = Decimal(0)  # credits the review LLM call used (settled below)
        surface: dict[str, Any] | None = None
        try:
            platform = ctx.platforms(s, repo)
            creds = platform.clone_credentials(ref)
            with sandbox_session(
                ctx.sandboxes,
                f"security-{scan.id}",
                mem_mb=settings.sandbox_mem_mb,
                cpus=settings.sandbox_cpus,
            ) as sb:
                sb.clone(creds, scan.branch, 1)
                sb.seal()
                head = sb.exec(["git", "rev-parse", "HEAD"], timeout_s=30, max_output_kb=4)
                scan.commit_sha = head.stdout.strip()[:64] if head.ok else ""
                surface = run_surface(ctx, sb)
                result: dict[str, Any] = {"surface": surface}
                if review:
                    raw, llm = run_review_llm(
                        ctx, sb, surface, org.id, repo.full_name, scan_id=scan.id
                    )
                    report = clean_report(raw, repo_host(repo.provider, settings))
                    result["report"] = report.model_dump(mode="json")
                    scan.input_tokens = llm.usage.input_tokens
                    scan.output_tokens = llm.usage.output_tokens
                    scan.cost_usd = llm.cost_usd
                    metered = llm.credits
            scan.result = result
            scan.summary = (
                f"Overall risk: {report.overall_risk}. {len(report.risks)} risks. "
                + surface_summary(surface)
                if report is not None
                else surface_summary(surface)
            )[:2000]
            scan.status, scan.finished_at = "completed", utcnow()
            if hold is not None:
                scan.credits_charged = ctx.ledger.settle(
                    s, hold, metered, settings.security_min_charge, final_reason=LEDGER_REASON
                )
            s.commit()
            _notify(ctx, s, platform, ref, scan, org, report, surface)
        except Exception as exc:
            log.exception("security_scan_failed", scan_id=str(scan_id))
            s.rollback()
            scan = s.get(SecurityScan, scan_id, populate_existing=True) or scan
            if hold is not None:
                ctx.ledger.release(s, hold)
            msg = str(exc) if isinstance(exc, SecurityJobError) else "The security job failed."
            scan.status, scan.error, scan.finished_at = "failed", msg, utcnow()
            scan.summary = f"{msg} No credit was charged." if hold is not None else msg
            s.commit()
            _notify(ctx, s, platform, ref, scan, org, None, None)
        finally:
            if platform is not None:
                close_platform(platform)
