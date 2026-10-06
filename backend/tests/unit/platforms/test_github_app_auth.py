import httpx
import jwt
import respx
from cryptography.hazmat.primitives import serialization

from app.platforms.github.app_auth import GitHubAppAuth
from tests.fakes.kv import DictKV

NOW = 1_800_000_000.0


def make(rsa_pem: str, kv: DictKV) -> GitHubAppAuth:
    return GitHubAppAuth("12345", rsa_pem, kv, "https://api.github.com", clock=lambda: NOW)


def test_app_jwt_is_rs256_with_issuer(rsa_pem: str) -> None:
    token = make(rsa_pem, DictKV()).app_jwt()
    pub = serialization.load_pem_private_key(rsa_pem.encode(), None).public_key()
    claims = jwt.decode(
        token, pub, algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
    )
    assert claims["iss"] == "12345"
    assert claims["exp"] - claims["iat"] <= 600


@respx.mock
def test_installation_token_is_cached_until_five_minutes_before_expiry(rsa_pem: str) -> None:
    route = respx.post("https://api.github.com/app/installations/42/access_tokens").mock(
        return_value=httpx.Response(
            201, json={"token": "ghs_abc", "expires_at": "2027-01-15T09:00:00Z"}
        )
    )
    kv = DictKV()
    auth = make(rsa_pem, kv)
    assert auth.installation_token(42) == "ghs_abc"
    assert auth.installation_token(42) == "ghs_abc"
    assert route.call_count == 1
    expires = 1_800_003_600  # 2027-01-15T09:00:00Z
    assert kv.ttls["gh:insttoken:42"] == int(expires - NOW - 300) == 3300
    assert route.calls[0].request.headers["Authorization"].startswith("Bearer ")


@respx.mock
def test_list_installation_repositories_uses_installation_token(rsa_pem: str) -> None:
    kv = DictKV({"gh:insttoken:42": "ghs_cached"})
    route = respx.get("https://api.github.com/installation/repositories").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 1,
                "repositories": [
                    {"id": 1001, "full_name": "acme/web", "private": True, "default_branch": "main"}
                ],
            },
        )
    )
    repos = make(rsa_pem, kv).list_installation_repositories(42)
    assert repos[0]["full_name"] == "acme/web"
    assert route.calls[0].request.headers["Authorization"] == "Bearer ghs_cached"
