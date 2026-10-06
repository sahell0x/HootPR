import httpx
import pytest

pytestmark = pytest.mark.integration


async def test_meta(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/meta")).json()
    assert body["github_app_slug"] == "hootpr-test"
    assert body["github_install_url"] == "https://github.com/apps/hootpr-test/installations/new"
    assert body["gitlab_base_url"] == "https://gitlab.com"
    assert body["razorpay_key_id"] == "rzp_test_key123" and body["billing_test_mode"] is True
    assert body["credit_pack"] == {"credits": 500, "price_paise": 4900, "currency": "INR"}
    assert "test mode" in body["disclaimer"] and "no real money" in body["disclaimer"]
    assert "**" not in body["disclaimer"]
    assert body["providers_enabled"] == {"github": True, "gitlab": True}
    assert body["credit_prices"] == {
        "per_review": "100",
        "per_chat_reply": "50",
        "signup_bonus": "300",
    }


def test_disclaimer_is_verbatim() -> None:
    from app.billing.disclaimer import DISCLAIMER, DISCLAIMER_PLAIN

    assert DISCLAIMER == (
        "Payments run in Razorpay **test mode** — no real money is charged or accepted. "
        "Use Razorpay's test card or UPI details at checkout."
    )
    assert DISCLAIMER.replace("**", "") == DISCLAIMER_PLAIN
