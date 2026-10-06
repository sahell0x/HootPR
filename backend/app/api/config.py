"""`.hootpr.yaml` JSON Schema + "Validate YAML" (spec §9.2, §9.3)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.schemas import ConfigError, ConfigValidation, ValidateConfigRequest
from app.config.schema import config_json_schema
from app.config.validator import validate_yaml
from app.deps import CurrentUser, SettingsDep

router = APIRouter()


@router.post("/api/config/validate", response_model=ConfigValidation)
async def validate(body: ValidateConfigRequest, user: CurrentUser) -> ConfigValidation:
    v = validate_yaml(body.yaml)
    return ConfigValidation(
        valid=v.valid,
        errors=[ConfigError(line=e.line, path=e.path, message=e.message) for e in v.errors],
        effective=v.config.model_dump(mode="json") if v.config else None,
    )


@router.get("/schema/hootpr.v1.json", include_in_schema=False)
@router.get("/api/schema/hootpr.v1.json", include_in_schema=False)
async def schema(settings: SettingsDep) -> JSONResponse:
    return JSONResponse(
        config_json_schema(settings.api_base_url),
        headers={"Cache-Control": "public, max-age=3600"},
    )
