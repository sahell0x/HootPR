"""Razorpay Orders API + signatures, TEST MODE ONLY (spec §6.7, decision P2)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

from app.settings import Settings


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_payment_signature(
    key_secret: str, order_id: str, payment_id: str, signature: str
) -> bool:
    """Checkout handler signature: HMAC-SHA256(key_secret, "order_id|payment_id")."""
    if not key_secret or not signature:
        return False
    expected = _hmac_hex(key_secret, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(webhook_secret: str, body: bytes, signature: str | None) -> bool:
    """``X-Razorpay-Signature``: HMAC-SHA256(webhook_secret, raw body)."""
    if not webhook_secret or not signature:
        return False
    return hmac.compare_digest(_hmac_hex(webhook_secret, body), signature)


class RazorpayError(Exception):
    pass


class RazorpayClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http

    async def create_order(
        self, *, amount_paise: int, receipt: str, notes: dict[str, str]
    ) -> dict[str, Any]:
        try:
            resp = await self._http.post(
                f"{self._s.razorpay_api_url.rstrip('/')}/orders",
                auth=(self._s.razorpay_key_id, self._s.razorpay_key_secret.get_secret_value()),
                json={
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt,
                    "notes": notes,
                },
            )
        except httpx.HTTPError as exc:
            raise RazorpayError(f"order creation failed: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise RazorpayError(f"order creation failed: HTTP {resp.status_code}")
        data: dict[str, Any] = resp.json()
        if not data.get("id"):
            raise RazorpayError("order creation returned no id")
        return data
