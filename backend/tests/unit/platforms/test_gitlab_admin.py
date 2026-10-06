import json

import httpx
import pytest
import respx

from app.platforms.base import PlatformError
from app.platforms.gitlab.admin import GitLabAdmin

API = "https://gitlab.com/api/v4"


@respx.mock
def test_current_user_and_bad_token() -> None:
    respx.get(f"{API}/user").mock(
        side_effect=[
            httpx.Response(200, json={"id": 5, "username": "hootpr-bot"}),
            httpx.Response(401),
        ]
    )
    admin = GitLabAdmin("tok", base_url="https://gitlab.com")
    assert admin.current_user()["username"] == "hootpr-bot"
    with pytest.raises(PlatformError) as ei:
        admin.current_user()
    assert ei.value.status_code == 401


@respx.mock
def test_install_hook_creates_with_all_events() -> None:
    respx.get(f"{API}/projects/2002/hooks").mock(return_value=httpx.Response(200, json=[]))
    create = respx.post(f"{API}/projects/2002/hooks").mock(
        return_value=httpx.Response(201, json={"id": 31})
    )
    hook_id = GitLabAdmin("tok", base_url="https://gitlab.com").install_hook(
        2002, "https://hootpr.dev/api/webhooks/gitlab", "sekret"
    )
    assert hook_id == 31
    body = json.loads(create.calls[0].request.content)
    assert body["token"] == "sekret" and body["enable_ssl_verification"] is True
    for ev in (
        "merge_requests_events",
        "note_events",
        "issues_events",
        "pipeline_events",
        "push_events",
    ):
        assert body[ev] is True


@respx.mock
def test_install_hook_updates_existing_same_url() -> None:
    url = "https://hootpr.dev/api/webhooks/gitlab"
    respx.get(f"{API}/projects/2002/hooks").mock(
        return_value=httpx.Response(200, json=[{"id": 8, "url": url}])
    )
    put = respx.put(f"{API}/projects/2002/hooks/8").mock(
        return_value=httpx.Response(200, json={"id": 8})
    )
    assert GitLabAdmin("tok", base_url="https://gitlab.com").install_hook(2002, url, "new") == 8
    assert put.call_count == 1


@respx.mock
def test_list_group_projects() -> None:
    route = respx.get(f"{API}/groups/10/projects").mock(
        return_value=httpx.Response(
            200, json=[{"id": 2002, "path_with_namespace": "acme-group/api"}]
        )
    )
    projects = GitLabAdmin("tok", base_url="https://gitlab.com").list_group_projects("10")
    assert projects[0]["id"] == 2002
    params = route.calls[0].request.url.params
    assert params["include_subgroups"] == "true" and params["min_access_level"] == "30"
