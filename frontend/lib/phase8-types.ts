// Phase 8 (analytics, reports, audit, API keys, Change Stack) API types — aliases of the generated
// OpenAPI schema. Decimals arrive as strings.
import type { components } from "./openapi";

type S = components["schemas"];
export type Period = S["Period"];
export type CountItem = S["CountItem"];
export type DayPoint = S["DayPoint"];
export type DurationStats = S["DurationStats"];
export type AcceptanceStats = S["AcceptanceStats"];
export type RepoBreakdown = S["RepoBreakdown"];
export type AuthorBreakdown = S["AuthorBreakdown"];
export type Metrics = S["Metrics"];
export type UsageLedgerEntry = S["UsageLedgerEntry"];
export type UsageReview = S["UsageReview"];
export type Usage = S["Usage"];

export type ReportSchedule = S["ReportDef"]["schedule"];
export type ReportRunStatus = S["ReportRunSummary"]["status"];
export type ReportDef = S["ReportDef"];
export type ReportDefList = S["ReportDefList"];
export type ReportDefIn = S["ReportDefIn"];
export type ReportRunSummary = S["ReportRunSummary"];
export type ReportRunDetail = S["ReportRunDetail"];
export type ReportRunList = S["ReportRunList"];
export type CustomReportIn = S["CustomReportIn"];

export type AuditEntry = S["AuditEntry"];
export type AuditList = S["AuditList"];
export type ApiKey = S["ApiKeyOut"];
export type ApiKeyList = S["ApiKeyList"];
export type ApiKeyCreated = S["ApiKeyCreated"];

export type CsPull = S["CsPull"];
export type CsSnapshot = S["CsSnapshot"];
export type CsFile = S["CsFile"];
export type CsGroup = S["CsGroup"];
export type CsFinding = S["CsFinding"];
export type CsViewer = S["CsViewer"];
export type CsWorkspace = S["CsWorkspace"];
export type CsFileContents = S["CsFileContents"];
export type CsMessage = S["CsMessage"];
export type ReviewEvent = S["CsReviewIn"]["event"];
export type CsReviewComment = S["CsReviewComment"];
export type CsReviewIn = S["CsReviewIn"];
export type MergeMethod = "merge" | "squash" | "rebase";
export type CsMergeOut = S["CsMergeOut"];
