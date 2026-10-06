"""Thin sync httpx client shared by GitHub/GitLab (plan decision P1)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import httpx

from app.platforms.base import NotFoundError, PlatformError


class HttpClient:
    def __init__(
        self,
        base_url: str,
        headers: Mapping[str, str],
        *,
        auth: httpx.Auth | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=dict(headers), auth=auth, timeout=timeout
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            resp = self._client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise PlatformError(0, f"{method} {path}: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise NotFoundError(404, f"{method} {path}: not found")
        if resp.status_code >= 400:
            raise PlatformError(
                resp.status_code, f"{method} {path}: HTTP {resp.status_code} {resp.text[:300]}"
            )
        return resp

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params).json()

    def paginate(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        item_key: str | None = None,
        max_pages: int = 50,
    ) -> Iterator[Any]:
        """Yield items across pages, following ``Link: rel="next"`` (GitHub and GitLab)."""
        url = path
        query: dict[str, Any] | None = {"per_page": 100, **(params or {})}
        for _ in range(max_pages):
            resp = self.request("GET", url, params=query)
            data = resp.json()
            yield from (data[item_key] if item_key else data)
            nxt = resp.links.get("next")
            if not nxt or not nxt.get("url"):
                return
            url, query = nxt["url"], None

    def close(self) -> None:
        self._client.close()
