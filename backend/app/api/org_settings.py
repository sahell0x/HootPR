"""Org-level review settings (spec §9.1 level 3) + knowledge-base opt-out."""

from fastapi import APIRouter
from sqlalchemy import delete

from app.analytics.audit import audit, changed_keys
from app.api.schemas import OrgSettings, SettingsUpdate
from app.config.validator import validate_settings
from app.deps import Db, OrgAdmin, OrgMember
from app.errors import invalid_settings_error
from app.models import Learning

router = APIRouter()


@router.get("/api/orgs/{org_slug}/settings", response_model=OrgSettings)
async def get_settings(ctx: OrgMember) -> OrgSettings:
    return OrgSettings(
        settings=ctx.org.settings or {}, knowledge_base_opt_out=ctx.org.knowledge_base_opt_out
    )


@router.put("/api/orgs/{org_slug}/settings", response_model=OrgSettings)
async def put_settings(body: SettingsUpdate, ctx: OrgAdmin, db: Db) -> OrgSettings:
    issues = validate_settings(body.settings)
    if issues:
        raise invalid_settings_error(issues)
    org = ctx.org
    before_settings, before_opt_out = dict(org.settings or {}), org.knowledge_base_opt_out
    org.settings = body.settings
    opt_out = (
        body.knowledge_base_opt_out
        if body.knowledge_base_opt_out is not None
        else org.knowledge_base_opt_out
    )
    kb = body.settings.get("knowledge_base")
    if isinstance(kb, dict) and kb.get("opt_out") is True:
        opt_out = True
    org.knowledge_base_opt_out = opt_out
    if opt_out:
        # Opting out deletes every stored learning (CodeRabbit parity, spec §8).
        await db.execute(delete(Learning).where(Learning.org_id == org.id))
    audit(
        db,
        org.id,
        "org.settings_updated",
        actor=ctx.user,
        target_type="organization",
        target_id=org.id,
        details={
            "changed": changed_keys(before_settings, body.settings),
            "knowledge_base_opt_out": [before_opt_out, opt_out],
        },
    )
    await db.commit()
    return OrgSettings(settings=org.settings, knowledge_base_opt_out=org.knowledge_base_opt_out)
