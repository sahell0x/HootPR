"""GitLab v4 REST client factory (plan decision P1: plain httpx, mockable with respx)."""

from __future__ import annotations

from app.platforms.http import HttpClient


def gitlab_client(base_url: str, token: str) -> HttpClient:
    return HttpClient(
        f"{base_url.rstrip('/')}/api/v4", {"PRIVATE-TOKEN": token, "User-Agent": "HootPR"}
    )
