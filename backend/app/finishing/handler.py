"""``@hootpr <finishing touch>`` → a queued ``finishing.run`` job (spec §8, §10.1).

Runs inline in ``events.process`` like the other commands: checks the config switch / recipe,
takes one ``review`` rate-limit slot, holds up to ``FINISHING_HOLD_MAX`` (``ref_type=
"finishing"``, settled at the metered credits when something is delivered, else released) and
acknowledges the request. The job later edits that acknowledgement with the result.
"""

from __future__ import annotations

from app.billing.ledger import InsufficientCredits
from app.billing.rate_limit import Limited
from app.chat.actions import CommandContext, _finish
from app.chat.replies import render_hint
from app.finishing.commands import CONFIG_KEYS, enabled, find_recipe, parse_finishing
from app.finishing.replies import (
    render_disabled,
    render_out_of_credits,
    render_queued,
    render_rate_limited,
    render_unknown_recipe,
)
from app.logging import get_logger
from app.models import FinishingJob

log = get_logger(__name__)
FINISHING_REF_TYPE = "finishing"
FINISHING_TASK = "finishing.run"


def handle_finishing(c: CommandContext) -> None:
    req = parse_finishing(c.parsed.phrase)
    if req is None:
        _finish(c, render_hint(c.author, f"Unknown command. Use `{c.mention} help`."))
        return
    if req.kind == "custom":
        recipe = find_recipe(c.cfg, req.recipe or "")
        if recipe is None or not recipe.enabled:
            names = [r.name for r in c.cfg.reviews.finishing_touches.custom if r.enabled]
            _finish(c, render_unknown_recipe(c.author, req.recipe or "", names))
            return
        recipe_name: str | None = recipe.name
    else:
        recipe_name = None
        if not enabled(c.cfg, req.kind):
            _finish(c, render_disabled(c.author, c.parsed.phrase, CONFIG_KEYS[req.kind]))
            return
    if c.pr.state != "open":
        _finish(c, render_hint(c.author, "Finishing touches only run on open pull requests."))
        return
    settings = c.ctx.settings
    limited = c.ctx.limiter.check_and_consume(c.org.id, "review")
    if isinstance(limited, Limited):
        log.info("finishing_rate_limited", retry_after_s=limited.retry_after_s)
        _finish(
            c,
            render_rate_limited(
                c.author, settings.rate_limit_reviews_per_hour, limited.retry_after_s
            ),
            status="rate_limited",
        )
        return
    job = FinishingJob(
        org_id=c.org.id,
        pr_id=c.pr.id,
        chat_message_id=c.row.id,
        kind=req.kind,
        recipe_name=recipe_name,
        trigger="command",
        delivery=req.delivery,
        status="queued",
        requested_by=c.author[:255],
        head_sha=c.pr.head_sha or "",
        meta={},
    )
    c.s.add(job)
    c.s.flush()
    cost = settings.finishing_min_charge
    hold = c.ctx.ledger.reserve_up_to(
        c.s, c.org.id, settings.finishing_hold_max, cost, FINISHING_REF_TYPE, job.id
    )
    if isinstance(hold, InsufficientCredits):
        job.status = "no_credits"
        log.info("finishing_no_credits", balance=str(hold.balance))
        _finish(
            c,
            render_out_of_credits(c.author, hold.balance, cost, c.billing_url()),
            status="no_credits",
        )
        return
    c.s.commit()
    try:
        c.ctx.queue.enqueue(FINISHING_TASK, str(job.id))
    except Exception as exc:
        log.exception("finishing_enqueue_failed")
        held = c.ctx.ledger.find_open_reservation(c.s, FINISHING_REF_TYPE, job.id)
        if held is not None:
            c.ctx.ledger.release(c.s, held)
        job.status, job.error = "failed", f"EnqueueFailed: {type(exc).__name__}"
        _finish(
            c,
            render_hint(c.author, "HootPR could not start this right now, no credit was charged."),
            status="failed",
        )
        return
    log.info("finishing_queued", kind=req.kind, delivery=req.delivery, job_id=str(job.id))
    _finish(c, render_queued(c.author, req.kind, recipe_name, req.delivery, c.pr.head_ref))
