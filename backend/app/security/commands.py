"""``@hootpr security review`` (spec §10.3): queue a repo-level security architecture review."""

from __future__ import annotations

from app.billing.pricing import fmt_credits
from app.chat.actions import CommandContext, _finish
from app.chat.replies import render_actions, render_hint
from app.logging import get_logger
from app.models import SecurityScan
from app.security.store import TASK, active_scan

log = get_logger(__name__)


def handle_security_review(c: CommandContext) -> None:
    settings = c.ctx.settings
    cost = settings.security_min_charge  # metered; refused only below the minimum charge
    base = settings.app_base_url.rstrip("/")
    url = f"{base}/o/{c.org.slug}/security"
    if active_scan(c.s, c.repo.id, "security_review") is not None:
        _finish(c, render_hint(c.author, f"A security review is already running — see {url}."))
        return
    balance = c.ctx.ledger.balance(c.s, c.org.id)
    if balance < cost:
        _finish(
            c,
            render_hint(
                c.author,
                f"A security review needs at least {fmt_credits(cost)} credits to start and the "
                f"balance is {fmt_credits(balance)}. An admin can top up at {c.billing_url()}.",
            ),
        )
        return
    branch = c.repo.default_branch or "main"
    scan = SecurityScan(
        org_id=c.org.id,
        repo_id=c.repo.id,
        kind="security_review",
        status="queued",
        trigger="command",
        requested_by=c.author[:255],
        pr_id=c.pr.id,
        chat_message_id=c.row.id,
        branch=branch,
    )
    c.s.add(scan)
    c.s.commit()
    try:
        c.ctx.queue.enqueue(TASK, str(scan.id))
    except Exception as exc:
        log.exception("security_enqueue_failed")
        scan.status, scan.error = "failed", f"EnqueueFailed: {type(exc).__name__}"[:2000]
        _finish(c, render_hint(c.author, "HootPR could not start the security review right now."))
        return
    _finish(
        c,
        render_actions(
            c.author,
            [f"Security architecture review of `{branch}` started."],
            "It is metered by AI usage, up to "
            f"{fmt_credits(settings.security_hold_max)} credits (refunded if it fails). The "
            f"report will be posted here and on the dashboard: {url}",
        ),
    )
