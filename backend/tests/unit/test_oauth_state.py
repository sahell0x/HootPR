import base64
import hashlib

from app.auth.oauth_state import pkce_pair, safe_next


def test_safe_next() -> None:
    assert safe_next(None) == "/orgs"
    assert safe_next("") == "/orgs"
    assert safe_next("/o/acme/repos?x=1") == "/o/acme/repos?x=1"
    assert safe_next("//evil.com") == "/orgs"
    assert safe_next("https://evil.com") == "/orgs"
    assert safe_next("/\\evil.com") == "/orgs"
    assert safe_next("/ok\r\nSet-Cookie: x=1") == "/orgs"


def test_pkce_pair_s256() -> None:
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert pkce_pair()[0] != verifier
