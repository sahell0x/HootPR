import httpx
import pytest
import respx

from app.platforms.base import NotFoundError, PlatformError
from app.platforms.http import HttpClient


@respx.mock
def test_paginate_follows_link_header() -> None:
    respx.get("https://api.test/items", params={"per_page": "100"}).mock(
        return_value=httpx.Response(
            200, json=[1, 2], headers={"Link": '<https://api.test/items?page=2>; rel="next"'}
        )
    )
    respx.get("https://api.test/items", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[3])
    )
    assert list(HttpClient("https://api.test", {}).paginate("/items")) == [1, 2, 3]


@respx.mock
def test_errors_are_mapped() -> None:
    respx.get("https://api.test/missing").mock(return_value=httpx.Response(404))
    respx.get("https://api.test/boom").mock(return_value=httpx.Response(502, text="bad"))
    c = HttpClient("https://api.test", {})
    with pytest.raises(NotFoundError):
        c.get_json("/missing")
    with pytest.raises(PlatformError) as ei:
        c.get_json("/boom")
    assert ei.value.status_code == 502
