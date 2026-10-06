"""Provider-neutral types for Phase 4 platform writes (spec §4.1 "later phases", §10.1).

Kept apart from ``base.py`` so it has no imports of its own (``base`` re-exports nothing from here
except the types its protocol stubs mention).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class PushRejected(Exception):
    """The branch moved (non-fast-forward) or the provider refused the push."""


@dataclass(frozen=True)
class FileChange:
    """One file of a commit, relative to the commit's base tree.

    ``content=None`` deletes the file. ``is_new`` tells providers that distinguish create/update
    (GitLab's Commits API) which action to use."""

    path: str
    content: bytes | None = field(repr=False)
    executable: bool = False
    is_new: bool = False


@dataclass(frozen=True)
class CiJobLog:
    """A failed CI job and the tail of its log (GitHub Actions job / GitLab pipeline job)."""

    job_id: str
    name: str
    status: str
    url: str
    log_tail: str = field(repr=False)
    run_id: str = ""
    run_name: str = ""
    failed_step: str | None = None


_BRANCH_BAD = re.compile(r"[^A-Za-z0-9._/-]+")


def branch_name(kind: str, pr_number: int, job_id: str) -> str:
    """A safe stacked-PR branch name, e.g. ``hootpr/docstrings-12-0192ab34``."""
    kind = _BRANCH_BAD.sub("-", kind).strip("-/.") or "change"
    return f"hootpr/{kind}-{pr_number}-{job_id.replace('-', '')[:8]}"


def tail_text(text: str, max_kb: int) -> str:
    """The last ``max_kb`` KiB of a log (failures are at the end), prefixed when cut."""
    raw = text.encode(errors="replace")
    limit = max(1, max_kb) * 1024
    if len(raw) <= limit:
        return text
    return "…[log truncated]\n" + raw[-limit:].decode(errors="ignore")
