"""``web_search(query)`` behind ``SEARCH_PROVIDER`` (spec §10.4). Off by default.

``brave`` is a preset; ``http`` is a generic JSON-over-HTTP provider configured entirely from
``.env`` (URL, key header, query parameter, dotted path to the results array).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.settings import Settings

MAX_QUERY_CHARS = 400
SNIPPET_CHARS = 300
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class SearchError(Exception):
    pass


@dataclass(frozen=True)
class SearchConfig:
    url: str
    api_key: str
    key_header: str
    query_param: str
    results_path: str
    max_results: int
    timeout_s: float


def search_config(settings: Settings) -> SearchConfig | None:
    provider = settings.search_provider.strip().lower()
    key = settings.search_api_key.get_secret_value()
    if provider == "brave":
        return SearchConfig(
            settings.search_api_url or BRAVE_URL,
            key,
            settings.search_api_key_header or "X-Subscription-Token",
            "q",
            "web.results",
            settings.search_max_results,
            settings.search_timeout_s,
        )
    if provider == "http" and settings.search_api_url:
        return SearchConfig(
            settings.search_api_url,
            key,
            settings.search_api_key_header,
            settings.search_query_param,
            settings.search_results_path,
            settings.search_max_results,
            settings.search_timeout_s,
        )
    return None


def _dig(data: Any, path: str) -> Any:
    for part in [p for p in path.split(".") if p]:
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _first(item: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


class WebSearch:
    def __init__(self, cfg: SearchConfig, http: httpx.Client | None = None) -> None:
        self._cfg = cfg
        self._own = http is None
        self._http = http or httpx.Client(timeout=cfg.timeout_s, follow_redirects=False)

    def close(self) -> None:
        if self._own:
            self._http.close()

    def search(self, query: str) -> str:
        q = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not q:
            raise SearchError("empty query")
        headers = {"Accept": "application/json"}
        if self._cfg.api_key:
            name = self._cfg.key_header or "Authorization"
            value = self._cfg.api_key
            headers[name] = f"Bearer {value}" if name.lower() == "authorization" else value
        try:
            resp = self._http.get(self._cfg.url, params={self._cfg.query_param: q}, headers=headers)
        except httpx.HTTPError as exc:
            raise SearchError(f"search request failed ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise SearchError(f"search provider returned HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchError("search provider sent invalid JSON") from exc
        items = _dig(data, self._cfg.results_path) if self._cfg.results_path else data
        if not isinstance(items, list):
            return "no results"
        lines: list[str] = []
        for item in items[: self._cfg.max_results]:
            if not isinstance(item, dict):
                continue
            title = _first(item, "title", "name")
            url = _first(item, "url", "link", "href")
            snippet = _first(item, "description", "snippet", "content", "body")
            lines.append(f"- {title}\n  {url}\n  {' '.join(snippet.split())[:SNIPPET_CHARS]}")
        return "\n".join(lines) or "no results"
