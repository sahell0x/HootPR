"""PR context shared by the Phase 5 prompts (all repo text wrapped as untrusted, spec §7.8)."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlparse

from app.platforms.base import FileDiff, ProviderName
from app.review.safety import untrusted
from app.review.schemas import WalkthroughSummary
from app.settings import Settings

BODY_CHARS = 4000
DIFF_BUDGET_CHARS = 12000
PER_FILE_CHARS = 2000


def web_host(provider: ProviderName, settings: Settings) -> str:
    url = settings.github_web_url if provider == "github" else settings.gitlab_base_url
    return (urlparse(url).hostname or "").lower()


def render_pr_context(
    title: str,
    body: str,
    summary: WalkthroughSummary | None,
    files: Sequence[FileDiff],
    *,
    diff_budget: int = DIFF_BUDGET_CHARS,
) -> str:
    parts = [untrusted("pr", f"title: {title}\n\n{body[:BODY_CHARS]}")]
    if summary is not None:
        cohorts = "\n".join(f"- {', '.join(g.files)}: {g.summary}" for g in summary.changes)
        parts.append(untrusted("walkthrough", f"{summary.walkthrough}\n\n{cohorts}"[:4000]))
    lines = [f"{f.status} {f.path} (+{f.additions} -{f.deletions})" for f in files[:200]]
    parts.append("Changed files:\n" + untrusted("files", "\n".join(lines)))
    used = 0
    for f in files:
        if used >= diff_budget or not f.patch:
            continue
        chunk = f.patch[: min(PER_FILE_CHARS, diff_budget - used)]
        used += len(chunk)
        parts.append(f"### DIFF {f.path}\n" + untrusted(f"diff:{f.path}", chunk))
    return "\n\n".join(parts)
