"""Provider-neutral webhook events (spec §6.5). JSON-serializable for Celery."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

Provider = Literal["github", "gitlab"]
# ``pr_updated``: a GitLab MR update that is neither a push nor draft→ready (title, labels,
# thread resolution, approvals); it only refreshes the request-changes state.
PrEventKind = Literal[
    "pr_opened", "pr_synchronized", "pr_reopened", "pr_ready", "pr_closed", "pr_updated"
]
InstallationAction = Literal[
    "created", "deleted", "suspend", "unsuspend", "repos_added", "repos_removed"
]


class EventRepo(BaseModel):
    provider: Provider
    provider_repo_id: str
    full_name: str
    default_branch: str | None = None
    private: bool = False


class EventPR(BaseModel):
    number: int
    title: str
    body: str = ""
    author_username: str = ""
    state: Literal["open", "closed", "merged"] = "open"
    is_draft: bool = False
    base_ref: str = ""
    head_ref: str = ""
    base_sha: str = ""
    head_sha: str = ""
    labels: list[str] = Field(default_factory=list)
    url: str = ""


class PrEvent(BaseModel):
    kind: PrEventKind
    provider: Provider
    delivery_id: str
    repo: EventRepo
    pr: EventPR
    installation_id: int | None = None
    before_sha: str | None = None
    sender: str = ""


class CommentCreated(BaseModel):
    kind: Literal["comment_created"] = "comment_created"
    provider: Provider
    delivery_id: str
    repo: EventRepo
    pr_number: int
    comment_id: str
    author_username: str
    body: str
    thread_ref: str | None = None
    installation_id: int | None = None
    # Review (diff) comment metadata; top-level PR comments leave these unset.
    is_review_comment: bool = False
    path: str | None = None
    line: int | None = None
    diff_hunk: str | None = None
    url: str = ""
    # GitHub ``comment.author_association`` (OWNER/MEMBER/COLLABORATOR/CONTRIBUTOR/NONE...);
    # GitLab notes carry no access level (looked up via the platform when needed).
    author_association: str | None = None


class ThreadStatusChanged(BaseModel):
    """A review thread was resolved/unresolved (GitHub ``pull_request_review_thread``)."""

    kind: Literal["thread_status_changed"] = "thread_status_changed"
    provider: Provider
    delivery_id: str
    repo: EventRepo
    pr_number: int
    thread_ref: str
    resolved: bool
    installation_id: int | None = None


class InstallationAccount(BaseModel):
    id: str
    login: str
    type: Literal["User", "Organization"]
    avatar_url: str | None = None


class InstallationChanged(BaseModel):
    kind: Literal["installation_changed"] = "installation_changed"
    provider: Literal["github"] = "github"
    delivery_id: str
    action: InstallationAction
    installation_id: int
    account: InstallationAccount
    repositories_added: list[EventRepo] = Field(default_factory=list)
    repositories_removed: list[EventRepo] = Field(default_factory=list)


class PipelineFailed(BaseModel):
    kind: Literal["pipeline_failed"] = "pipeline_failed"
    provider: Provider
    delivery_id: str
    repo: EventRepo
    sha: str
    pr_number: int | None = None
    # Phase 4: the failed workflow run / pipeline and its branch
    run_id: str | None = None
    ref: str | None = None
    url: str = ""
    installation_id: int | None = None


class IssueOpened(BaseModel):
    """A new issue (Phase 5 enrichment): GitHub ``issues.opened``, GitLab issue ``open``."""

    kind: Literal["issue_opened"] = "issue_opened"
    provider: Provider
    delivery_id: str
    repo: EventRepo
    number: int
    title: str
    body: str = ""
    author_username: str = ""
    url: str = ""
    labels: list[str] = Field(default_factory=list)
    installation_id: int | None = None


PlatformEvent = Annotated[
    PrEvent
    | CommentCreated
    | ThreadStatusChanged
    | InstallationChanged
    | PipelineFailed
    | IssueOpened,
    Field(discriminator="kind"),
]
event_adapter: TypeAdapter[PlatformEvent] = TypeAdapter(PlatformEvent)
