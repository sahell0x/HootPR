"""Token-metered credits (docs/token-metered-billing.md §1-§5). Pure functions, no I/O.

HootPR's own rate card (credits per 1M tokens per gateway role), not provider $ x markup:
``credits = (fresh_input * in + cached * cached_rate + output * out) / 1M`` at 6 dp per call.
Holds are sized from the PR up front (whole credits) and settled at the metered credits rounded
up to a whole credit, clamped to ``[minimum, hold]`` (an overrun beyond the hold is absorbed by
HootPR). Every amount written to the ledger is a whole number of credits.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.llm.types import Usage
    from app.settings import Settings

# Charges, holds, balances and receipt lines are whole credits (quantized to ``CREDIT``).
CREDIT = Decimal(1)
MICRO = Decimal("0.000001")
_M = Decimal(1_000_000)
# Stop scheduling new agent tasks once this share of the hold is used (judge + walkthrough
# still need headroom).
BUDGET_HEADROOM = Decimal("0.85")
# Changed lines assumed per file when a platform only reports the file count (GitLab).
LINES_PER_FILE_GUESS = 40

PricedRole = Literal["review", "cheap", "embed"]

# Pipeline order; also the receipt / walkthrough order.
STAGE_LABELS: dict[str, str] = {
    "learnings": "Learnings",
    "triage": "Triage",
    "plan": "Planning",
    "agents": "Review agents",
    "judge": "Verification",
    "summarize": "Walkthrough",
    "merge_checks": "Merge checks",
    "chat": "Chat reply",
    "finishing": "Finishing touch",
    "security": "Security review",
    "other": "Other",
}
OTHER = "other"


@dataclass(frozen=True)
class Rate:
    input_per_1m: Decimal
    cached_per_1m: Decimal
    output_per_1m: Decimal


@dataclass(frozen=True)
class RateCard:
    review: Rate = Rate(Decimal(6000), Decimal(600), Decimal(12000))
    cheap: Rate = Rate(Decimal(2000), Decimal(200), Decimal(4000))
    embed: Rate = Rate(Decimal(200), Decimal(200), Decimal(0))

    def rate(self, role: PricedRole) -> Rate:
        rate: Rate = getattr(self, role)
        return rate


def rate_card(settings: Settings) -> RateCard:
    s = settings
    return RateCard(
        review=Rate(
            s.credits_review_input_per_1m,
            s.credits_review_cached_per_1m,
            s.credits_review_output_per_1m,
        ),
        cheap=Rate(
            s.credits_cheap_input_per_1m,
            s.credits_cheap_cached_per_1m,
            s.credits_cheap_output_per_1m,
        ),
        embed=Rate(
            s.credits_embed_input_per_1m,
            s.credits_embed_cached_per_1m,
            s.credits_embed_output_per_1m,
        ),
    )


def credits_for(role: PricedRole, usage: Usage, card: RateCard) -> Decimal:
    """Credits for one call (6 dp). Cached tokens are a subset of input tokens."""
    r = card.rate(role)
    cached = min(max(0, usage.cached_tokens), max(0, usage.input_tokens))
    fresh = max(0, usage.input_tokens - cached)
    total = (
        fresh * r.input_per_1m + cached * r.cached_per_1m + usage.output_tokens * r.output_per_1m
    ) / _M
    return total.quantize(MICRO, rounding=ROUND_HALF_UP)


def stage_key(stage: str | None) -> str:
    return stage if stage in STAGE_LABELS else OTHER


def stage_label(stage: str | None) -> str:
    return STAGE_LABELS[stage_key(stage)]


def ordered_stages(by_stage: dict[str, Decimal]) -> list[tuple[str, Decimal]]:
    """``(stage, credits)`` in pipeline order, unknown keys folded into ``other``."""
    merged: dict[str, Decimal] = {}
    for k, v in by_stage.items():
        key = stage_key(k)
        merged[key] = merged.get(key, Decimal(0)) + Decimal(v)
    return [(k, merged[k]) for k in STAGE_LABELS if k in merged]


def whole(value: Decimal | int) -> Decimal:
    """Quantize to whole credits (half-up) for display / API values."""
    return Decimal(value).quantize(CREDIT, rounding=ROUND_HALF_UP)


def ceil_whole(value: Decimal | int) -> Decimal:
    """Round up to a whole credit."""
    return Decimal(value).quantize(CREDIT, rounding=ROUND_CEILING)


def fmt_credits(value: Decimal | int) -> str:
    """User-facing credit amount: whole number with thousands separators (``1,250``)."""
    return f"{whole(value):,}"


def settle_amount(actual: Decimal, minimum: Decimal, hold: Decimal) -> Decimal:
    """``clamp(ceil_whole(actual), ceil_whole(minimum), hold)``; the hold always wins over the
    minimum."""
    charge = max(ceil_whole(actual), ceil_whole(minimum))
    return min(charge, ceil_whole(hold))


def distribute_whole(values: list[Decimal], total: Decimal) -> list[Decimal]:
    """Split whole ``total`` across ``values`` proportionally (largest remainder) so the whole
    parts add up exactly to ``total`` — receipt / walkthrough lines sum to the charge."""
    total = whole(total)
    weights = [max(Decimal(v), Decimal(0)) for v in values]
    base_sum = sum(weights, Decimal(0))
    if not weights or total <= 0 or base_sum <= 0:
        return [Decimal(0) for _ in values]
    exact = [w * total / base_sum for w in weights]
    floors = [e.to_integral_value(rounding=ROUND_FLOOR) for e in exact]
    left = int(total - sum(floors, Decimal(0)))
    order = sorted(
        range(len(exact)), key=lambda i: (exact[i] - floors[i], weights[i]), reverse=True
    )
    for i in order[:left]:
        floors[i] += 1
    return [f.quantize(CREDIT) for f in floors]


def estimate_review_hold(
    changed_lines: int | None, files: int | None, settings: Settings
) -> Decimal:
    """Review hold from the PR size (whole credits); unknown size reserves ``review_hold_max``.

    Files only (GitLab merge requests carry no line counts): lines are estimated at
    ``LINES_PER_FILE_GUESS`` per changed file."""
    s = settings
    if files is None:
        return ceil_whole(s.review_hold_max)
    if changed_lines is None:
        changed_lines = max(0, files) * LINES_PER_FILE_GUESS
    raw = (
        s.review_hold_base
        + max(0, changed_lines) * s.review_hold_per_line
        + max(0, files) * s.review_hold_per_file
    )
    clamped = min(max(raw, s.review_min_charge), s.review_hold_max)
    return ceil_whole(clamped)
