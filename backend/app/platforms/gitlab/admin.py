"""Bot-token operations used by the dashboard and the hook sync task (spec §6.4)."""

from __future__ import annotations

from typing import Any

from app.platforms.gitlab.client import gitlab_client

HOOK_EVENTS = (
    "merge_requests_events",
    "note_events",
    "issues_events",
    "pipeline_events",
    "push_events",
)
DEVELOPER_ACCESS = 30


class GitLabAdmin:
    def __init__(self, token: str, *, base_url: str) -> None:
        self._http = gitlab_client(base_url, token)

    def close(self) -> None:
        self._http.close()

    def current_user(self) -> dict[str, Any]:
        """The bot user; a revoked/invalid token raises ``PlatformError(401)``."""
        data: dict[str, Any] = self._http.get_json("/user")
        return data

    def list_group_projects(self, group_id: str) -> list[dict[str, Any]]:
        return list(
            self._http.paginate(
                f"/groups/{group_id}/projects",
                {
                    "include_subgroups": "true",
                    "min_access_level": DEVELOPER_ACCESS,
                    "archived": "false",
                    "with_shared": "false",
                },
            )
        )

    def list_user_projects(self, user_id: str) -> list[dict[str, Any]]:
        return list(
            self._http.paginate(
                f"/users/{user_id}/projects",
                {"min_access_level": DEVELOPER_ACCESS, "archived": "false"},
            )
        )

    def install_hook(self, project_id: int, url: str, secret: str) -> int:
        """Create the project webhook, or update ours in place if one with this URL exists."""
        payload: dict[str, Any] = {
            "url": url,
            "token": secret,
            "enable_ssl_verification": url.startswith("https://"),
            **dict.fromkeys(HOOK_EVENTS, True),
        }
        for hook in self._http.paginate(f"/projects/{project_id}/hooks"):
            if hook.get("url") == url:
                self._http.request(
                    "PUT", f"/projects/{project_id}/hooks/{hook['id']}", json=payload
                )
                return int(hook["id"])
        created = self._http.request("POST", f"/projects/{project_id}/hooks", json=payload).json()
        return int(created["id"])

    def remove_hook(self, project_id: int, hook_id: int) -> None:
        self._http.request("DELETE", f"/projects/{project_id}/hooks/{hook_id}")
