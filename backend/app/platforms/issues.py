"""Provider-neutral issue types for Phase 5 (spec §4.1 "later phases", §10.2).

Kept apart from ``base.py`` (no imports of its own) so the provider mixins and ``base`` can both
import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

IssueState = Literal["open", "closed"]


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    state: IssueState
    author_username: str
    labels: tuple[str, ...]
    url: str
    repo_full_name: str


def gitlab_project_id(provider_repo_id: str) -> str:
    """GitLab accepts a numeric project id or the URL-encoded ``group/project`` path. A
    ``RepoRef`` built for a foreign project (a linked issue) carries the path."""
    return provider_repo_id if provider_repo_id.isdigit() else quote(provider_repo_id, safe="")
