"""Public API keys: ``hpr_<40 urlsafe chars>``; only the SHA-256 hex digest is stored.

The secret carries 240 bits of randomness, so a fast hash is sufficient (no password
stretching needed) and lookups stay a single indexed equality on ``key_hash``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

KEY_PREFIX = "hpr_"
SECRET_CHARS = 40
DISPLAY_PREFIX_LEN = 12


@dataclass(frozen=True)
class NewKey:
    secret: str
    prefix: str
    key_hash: str


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_key() -> NewKey:
    body = secrets.token_urlsafe(SECRET_CHARS)[:SECRET_CHARS]
    secret = f"{KEY_PREFIX}{body}"
    return NewKey(secret=secret, prefix=secret[:DISPLAY_PREFIX_LEN], key_hash=hash_key(secret))


def looks_like_key(value: str | None) -> bool:
    return (
        bool(value)
        and value is not None
        and value.startswith(KEY_PREFIX)
        and len(value) == len(KEY_PREFIX) + SECRET_CHARS
    )


def matches(secret: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_key(secret), key_hash)


def extract_key(authorization: str | None, x_api_key: str | None) -> str | None:
    """``Authorization: Bearer hpr_…`` or ``X-API-Key: hpr_…``."""
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return None
