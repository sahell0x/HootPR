// API types, generated from FastAPI's OpenAPI schema (spec §12) so backend and dashboard cannot
// drift. `make api-types` regenerates lib/openapi.d.ts; tests/unit/api-types.test.ts fails when the
// committed file is stale. Only aliases live here; the error envelope (not in the schema) is the
// single hand-written type.
import type { components } from "./openapi";

type S = components["schemas"];

export type Provider = S["Identity"]["provider"];
export type Role = S["Member"]["role"];
export type OrgKind = S["Org"]["kind"];
export type ReviewStatus = S["ReviewSummary"]["status"];
export type ReviewTrigger = S["ReviewSummary"]["trigger"];
/** Token-metered billing (docs/token-metered-billing.md §6) adds settle/charge reasons; widened here so
 * the UI handles them before and after `make api-types` picks them up. */
export type LedgerReason = S["LedgerEntry"]["reason"] | "review" | "chat" | "finishing" | "security";

export type ConfigError = S["ConfigError"];

/** `app/errors.py` api_error() envelope, or FastAPI's 422 validation list. */
export interface ApiErrorBody {
  detail:
    | { code: string; message: string; errors?: ConfigError[] }
    | Array<{ loc: (string | number)[]; msg: string; type: string }>;
}

export type Identity = S["Identity"];
export type Me = S["Me"];

export type CreditPack = S["CreditPack"];
export type CreditPrices = S["CreditPrices"];
export type Meta = S["Meta"];

export type OrgCandidate = S["OrgCandidate"];
export type OrgCandidateList = S["OrgCandidateList"];
export type SelectOrgRequest = S["SelectOrgRequest"];
export type Org = S["Org"];
export type OrgList = S["OrgList"];

export type OrgSettings = S["OrgSettings"];
export type SettingsUpdate = S["SettingsUpdate"];

export type Member = S["Member"];
export type MemberList = S["MemberList"];
export type RoleUpdate = S["RoleUpdate"];

export type Repo = S["Repo"];
export type RepoList = S["RepoList"];
export type UpdateRepoRequest = S["UpdateRepoRequest"];
export type RepoSettings = S["RepoSettings"];

export type GitlabBot = S["GitlabBot"];
export type GitlabBotRequest = S["GitlabBotRequest"];
export type GitlabProject = S["GitlabProject"];
export type GitlabProjectList = S["GitlabProjectList"];
export type GitlabProjectsRequest = S["GitlabProjectsRequest"];

export type ReviewSummary = S["ReviewSummary"];
export type ReviewList = S["ReviewList"];
export type Finding = S["Finding"];
export type LlmCall = S["LlmCall"];
export type AgentStep = S["AgentStep"];
export type ToolRun = S["ToolRun"];
export type Trace = S["Trace"];
/** One metered stage of a review's credit receipt. Token / $ fields are platform-owner only (`null` or
 * absent for everyone else). Decimals arrive as strings. */
export interface ReceiptLine {
  stage: string;
  label: string;
  credits: string;
  input_tokens?: number | null;
  cached_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: string | null;
}
/** Reserve → meter → settle receipt for a metered job (review, chat, finishing touch, security review);
 * `null` when the job never held credits. `legacy`: billed at the flat rate used before usage metering. */
export interface CreditReceipt {
  reserved: string;
  charged: string;
  refunded: string;
  minimum_applied: boolean;
  budget_reached: boolean;
  legacy?: boolean;
  lines: ReceiptLine[];
}
export type ReviewDetail = Omit<S["ReviewDetail"], "receipt"> & { receipt?: CreditReceipt | null };
export type ReviewStage = S["ReviewStage"];
export type ReviewTask = S["ReviewTask"];
export type LlmCallDetail = S["LlmCallDetail"];
export type JudgeVerdict = NonNullable<Finding["judge_verdict"]>;
export type Severity = "critical" | "major" | "minor" | "nitpick";

/** `charged` is set on settle rows: the final charge (hold − returned). `description` / `href` say what the
 * movement was for; `has_receipt` means `api.receipt(slug, ref_type, ref_id)` returns its credit receipt. */
export type LedgerEntry = Omit<S["LedgerEntry"], "reason" | "charged" | "description" | "href" | "has_receipt"> & {
  reason: LedgerReason;
  charged?: string | null;
  description?: string | null;
  href?: string | null;
  has_receipt?: boolean;
};
/** Platform-owner only: last 30 days of metered credits, billed vs unbilled, and provider cost. */
export type OwnerUsage = S["OwnerUsage"];
export type UsageSource = S["UsageSource"];
/** How the org's credits are metered (billing endpoint). */
export interface Metering {
  review_min_charge: string;
  review_hold_max: string;
  chat_min_charge: string;
  avg_review_credits_30d: string | null;
  reviews_30d: number;
}
export type Billing = Omit<S["Billing"], "ledger" | "metering" | "usage_30d"> & {
  ledger: LedgerEntry[];
  metering?: Metering | null;
  usage_30d?: OwnerUsage | null;
};
export type Order = S["Order"];
export type VerifyPaymentRequest = S["VerifyPaymentRequest"];
export type VerifyResult = S["VerifyResult"];

export type ValidateConfigRequest = S["ValidateConfigRequest"];
export type ConfigValidation = S["ConfigValidation"];

export type Health = S["Health"];

export type Learning = S["Learning"];
export type LearningList = S["LearningList"];
export type LearningCreate = S["LearningCreate"];
export type LearningUpdate = S["LearningUpdate"];
export type LearningScope = Learning["scope"];
export type EffectiveConfig = S["EffectiveConfig"];
/** The published `.hootpr.yaml` JSON schema document (`/api/schema/hootpr.v1.json`, not in OpenAPI). */
export type ConfigSchema = Record<string, unknown>;
