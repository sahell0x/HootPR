import json
from pathlib import Path

from app.main import create_app
from app.settings import Settings

CONTRACT_SCHEMAS = {
    "Health",
    "Me",
    "Identity",
    "Meta",
    "CreditPack",
    "OrgCandidate",
    "OrgCandidateList",
    "SelectOrgRequest",
    "Org",
    "OrgList",
    "OrgSettings",
    "SettingsUpdate",
    "Member",
    "MemberList",
    "RoleUpdate",
    "Repo",
    "RepoList",
    "UpdateRepoRequest",
    "RepoSettings",
    "GitlabBot",
    "GitlabBotRequest",
    "GitlabProject",
    "GitlabProjectList",
    "GitlabProjectsRequest",
    "ReviewSummary",
    "ReviewList",
    "ReviewDetail",
    "Finding",
    "LlmCall",
    "AgentStep",
    "ToolRun",
    "Trace",
    "ReviewStage",
    "ReviewTask",
    "LlmCallDetail",
    "LedgerEntry",
    "Billing",
    "Order",
    "VerifyPaymentRequest",
    "VerifyResult",
    "ConfigError",
    "ValidateConfigRequest",
    "ConfigValidation",
}
CONTRACT_PATHS = {
    "/api/health",
    "/api/meta",
    "/api/me",
    "/api/auth/logout",
    "/api/auth/{provider}/login",
    "/api/auth/{provider}/callback",
    "/api/github/setup",
    "/api/orgs",
    "/api/orgs/candidates",
    "/api/orgs/select",
    "/api/orgs/{org_slug}",
    "/api/orgs/{org_slug}/settings",
    "/api/orgs/{org_slug}/members",
    "/api/orgs/{org_slug}/members/{user_id}",
    "/api/orgs/{org_slug}/repos",
    "/api/orgs/{org_slug}/repos/{repo_id}",
    "/api/orgs/{org_slug}/repos/{repo_id}/settings",
    "/api/orgs/{org_slug}/repos/sync",
    "/api/orgs/{org_slug}/gitlab/bot",
    "/api/orgs/{org_slug}/gitlab/projects",
    "/api/orgs/{org_slug}/reviews",
    "/api/orgs/{org_slug}/reviews/{review_id}",
    "/api/orgs/{org_slug}/reviews/{review_id}/llm-calls/{call_id}",
    "/api/orgs/{org_slug}/billing",
    "/api/orgs/{org_slug}/billing/orders",
    "/api/billing/verify",
    "/api/config/validate",
    "/api/webhooks/github",
    "/api/webhooks/gitlab",
    "/api/webhooks/razorpay",
}


def test_openapi_matches_contract() -> None:
    spec = create_app(Settings(_env_file=None)).openapi()  # type: ignore[call-arg]
    missing_schemas = CONTRACT_SCHEMAS - set(spec["components"]["schemas"])
    missing_paths = CONTRACT_PATHS - set(spec["paths"])
    assert not missing_schemas, missing_schemas
    assert not missing_paths, missing_paths
    billing = spec["components"]["schemas"]["Billing"]["properties"]["balance"]
    assert billing.get("type") == "string"  # decimals are strings in responses


def test_export_script_writes_committed_schema(tmp_path: Path) -> None:
    from app.scripts.export_openapi import main

    out = tmp_path / "openapi.json"
    assert main([str(out)]) == 0
    fresh = json.loads(out.read_text())
    assert "/api/orgs/{org_slug}/reviews" in fresh["paths"]
    committed = Path(__file__).resolve().parents[2] / "openapi.json"
    assert json.loads(committed.read_text()) == fresh, (
        "backend/openapi.json is stale: run `uv run python -m app.scripts.export_openapi`"
    )
