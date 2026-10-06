"use client";
import { TYPICAL_REVIEW_CREDITS, reviewsFor } from "@/lib/format";
import { useMeta } from "@/lib/queries";

/** Landing-page line; the bonus comes from /api/meta. Reviews are metered, so this counts typical (≈ 100 credits) reviews. */
export function SignupBonusNote() {
  const { data } = useMeta();
  const free = data ? reviewsFor(data.credit_prices.signup_bonus, TYPICAL_REVIEW_CREDITS) : 0;
  return (
    <p className="text-sm text-muted-foreground">
      Works with GitHub and GitLab.
      {free > 0 ? ` New organizations start with free credits — about ${free} typical ${free === 1 ? "review" : "reviews"}.` : null}
    </p>
  );
}
