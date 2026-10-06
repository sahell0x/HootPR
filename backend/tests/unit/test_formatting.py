from decimal import Decimal

from app.formatting.notices import (
    error_notice,
    out_of_credits_notice,
    rate_limited_notice,
    skip_title,
    skipped_notice,
)
from app.formatting.walkthrough import WALKTHROUGH_MARKER


def test_notices() -> None:
    rl = rate_limited_notice(2, 1500)
    assert rl.startswith(WALKTHROUGH_MARKER) and "rate limited" in rl.lower() and "25m" in rl
    assert "@hootpr rate limit" in rl
    oc = out_of_credits_notice(Decimal("0.50"), "http://localhost:3000/o/acme/billing")
    assert oc.startswith(WALKTHROUGH_MARKER)
    assert "Out of credits" in oc and "/o/acme/billing" in oc and "no real money" not in oc
    assert error_notice().startswith(WALKTHROUGH_MARKER)
    assert "no credit was charged" in error_notice()
    detailed = error_notice("The AI provider is unavailable right now.")
    assert "no credit was charged." in detailed and "\n\nThe AI provider is unavailable" in detailed
    assert skip_title("draft") == "Skipped: draft pull request"
    assert skip_title("something_new") == "Skipped: something_new"
    sk = skipped_notice("draft")
    assert sk.startswith(WALKTHROUGH_MARKER) and "draft pull request" in sk
