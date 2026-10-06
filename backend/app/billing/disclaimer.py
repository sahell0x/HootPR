"""Test-mode payment notice. Shown only where a user is about to pay, never site-wide."""

DISCLAIMER = (
    "Payments run in Razorpay **test mode** — no real money is charged or accepted. "
    "Use Razorpay's test card or UPI details at checkout."
)
DISCLAIMER_PLAIN = DISCLAIMER.replace("**", "")
