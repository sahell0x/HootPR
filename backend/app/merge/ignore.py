"""``@hootpr ignore pre-merge checks`` (spec §10.2): failing checks are overridden for this PR
(sticky across later reviews), the walkthrough table is rewritten in place and the HootPR status
turns green again."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select, update

from app.chat.actions import CommandContext, _finish
from app.chat.replies import render_actions, render_hint
from app.formatting.walkthrough import WALKTHROUGH_MARKER
from app.logging import get_logger
from app.merge.checks import CheckResult, any_blocking, render_pre_merge, replace_section
from app.merge.schemas import CheckStatus
from app.models import PreMergeResult

log = get_logger(__name__)
OVERRIDE_KIND = "override"


def _latest(c: CommandContext) -> list[PreMergeResult]:
    sha = c.s.execute(
        select(PreMergeResult.head_sha)
        .where(PreMergeResult.pr_id == c.pr.id, PreMergeResult.kind != OVERRIDE_KIND)
        .order_by(PreMergeResult.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if sha is None:
        return []
    return list(
        c.s.execute(
            select(PreMergeResult)
            .where(
                PreMergeResult.pr_id == c.pr.id,
                PreMergeResult.head_sha == sha,
                PreMergeResult.kind != OVERRIDE_KIND,
            )
            .order_by(PreMergeResult.created_at)
        ).scalars()
    )


def handle_ignore_pre_merge(c: CommandContext) -> None:
    rows = _latest(c)
    was_blocking = any_blocking([_result(r) for r in rows])
    c.s.execute(
        update(PreMergeResult)
        .where(
            PreMergeResult.pr_id == c.pr.id,
            PreMergeResult.status == "failed",
            PreMergeResult.ignored.is_(False),
        )
        .values(ignored=True, ignored_by=c.author[:255])
    )
    # Sticky marker: later reviews of this PR start with every failed check ignored.
    c.s.add(
        PreMergeResult(
            pr_id=c.pr.id,
            head_sha=c.pr.head_sha[:64],
            kind=OVERRIDE_KIND,
            name="ignore",
            mode="warning",
            status="passed",
            explanation="",
            ignored=True,
            ignored_by=c.author[:255],
        )
    )
    c.s.commit()
    results = [_result(r) for r in _latest(c)]
    if results:
        _rewrite_walkthrough(c, results)
    if was_blocking and c.cfg.reviews.commit_status and c.pr.head_sha:
        try:
            c.platform.set_status(
                c.ref,
                c.pr.head_sha,
                "success",
                "Pre-merge checks ignored",
                f"Failing pre-merge checks were ignored by @{c.author}.",
            )
        except Exception:
            log.warning("pre_merge_ignore_status_failed", exc_info=True)
    if not results:
        body = render_hint(
            c.author,
            "No pre-merge check results yet: failing checks of later reviews will be ignored.",
        )
    else:
        body = render_actions(c.author, ["Pre-merge checks override command executed."])
    _finish(c, body)


def _result(r: PreMergeResult) -> CheckResult:
    return CheckResult(
        r.kind, r.name, r.mode, cast(CheckStatus, r.status), r.explanation, r.ignored, r.ignored_by
    )


def _rewrite_walkthrough(c: CommandContext, results: list[CheckResult]) -> None:
    try:
        current = next(
            (
                x.body
                for x in c.platform.list_comments(c.ref, c.pr.number)
                if x.path is None and WALKTHROUGH_MARKER in x.body
            ),
            None,
        )
        if current is None:
            return
        updated = replace_section(current, render_pre_merge(results, c.mention))
        if updated is not None and updated != current:
            c.platform.upsert_comment(c.ref, c.pr.number, WALKTHROUGH_MARKER, updated)
    except Exception:
        log.warning("pre_merge_walkthrough_rewrite_failed", exc_info=True)
