"""SSRF guard + web_search provider (phase 7)."""

import httpx
import pytest
from pydantic import SecretStr

from app.kb.ssrf import UnsafeUrl, check_url, is_public_ip
from app.kb.web_search import WebSearch, search_config
from app.settings import Settings

PUBLIC = lambda h, p: ["93.184.216.34"]  # noqa: E731


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example.com/x",
        "ftp://mcp.example.com/x",
        "https://user:pw@mcp.example.com/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://10.1.2.3/x",
        "https://192.168.0.1/x",
        "https://172.16.0.1/x",
        "https://100.64.0.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/x",
        "https://[::ffff:127.0.0.1]/x",
        "https://[fd00::1]/x",
        "https://0.0.0.0/x",
        "https://metadata.google.internal/x",
        "https://svc.internal/x",
        "https://intranet/x",
        "https://mcp.example.com/x#frag",
    ],
)
def test_blocks_unsafe_urls(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        check_url(url, resolver=PUBLIC)


def test_blocks_hosts_resolving_to_private_addresses() -> None:
    with pytest.raises(UnsafeUrl):
        check_url("https://evil.example.com/", resolver=lambda h, p: ["93.184.216.34", "10.0.0.1"])


def test_allows_public_https_and_dev_overrides() -> None:
    assert check_url("https://mcp.example.com/mcp", resolver=PUBLIC)
    assert check_url("http://mcp.example.com/mcp", allow_http=True, resolver=PUBLIC)
    assert check_url("http://localhost:8080/mcp", allow_http=True, allow_private=True)
    assert is_public_ip("8.8.8.8") and not is_public_ip("fe80::1")


def test_production_refuses_mcp_dev_overrides(settings: Settings) -> None:
    data = settings.model_dump()
    data.update(app_env="production", sandbox_backend="docker", mcp_allow_private_hosts=True)
    with pytest.raises(ValueError, match="MCP_ALLOW"):
        Settings(_env_file=None, **data)  # type: ignore[call-arg]


def test_web_search_off_by_default_and_generic_http(settings: Settings) -> None:
    assert search_config(settings) is None
    s = settings.model_copy(
        update={
            "search_provider": "http",
            "search_api_url": "https://search.example.com/api",
            "search_api_key": SecretStr("k1"),
            "search_api_key_header": "X-Api-Key",
            "search_results_path": "data.items",
        }
    )
    cfg = search_config(s)
    assert cfg is not None
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        items = [{"title": "CVE-1", "link": "https://x.test/1", "snippet": "bad  lib"}]
        return httpx.Response(200, json={"data": {"items": items}})

    ws = WebSearch(cfg, httpx.Client(transport=httpx.MockTransport(handler)))
    out = ws.search("lib cve")
    assert "CVE-1" in out and "https://x.test/1" in out and "bad lib" in out
    assert seen[0].headers["x-api-key"] == "k1" and seen[0].url.params["q"] == "lib cve"
