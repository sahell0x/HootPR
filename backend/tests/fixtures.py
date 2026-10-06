import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "webhooks"


def fixture_bytes(provider: str, name: str) -> bytes:
    return (FIXTURES / provider / f"{name}.json").read_bytes()


def load_fixture(provider: str, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(fixture_bytes(provider, name))
    return data


def sign_github(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def sign_razorpay(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
