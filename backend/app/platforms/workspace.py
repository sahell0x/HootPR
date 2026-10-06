"""Provider-neutral types for Phase 8 Change Stack actions (spec §10.5).

``submit_review`` and ``merge_pull_request`` are called on a platform built with the signed-in
user's own OAuth token (``app.platforms.user``), never the bot's, so the provider records the
human as the reviewer / merger and enforces their permissions and branch protection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MergeMethod = Literal["merge", "squash", "rebase"]


@dataclass(frozen=True)
class UserReviewComment:
    path: str
    line: int
    body: str
    start_line: int | None = None
    side: Literal["LEFT", "RIGHT"] = "RIGHT"


@dataclass(frozen=True)
class MergeResult:
    merged: bool
    sha: str | None
    message: str
