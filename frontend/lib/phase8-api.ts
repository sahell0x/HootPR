"use client";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api";
import { apiUrl } from "./runtime-config";
import type * as P from "./phase8-types";

const o = (slug: string) => `/api/orgs/${encodeURIComponent(slug)}`;
const seg = encodeURIComponent;
const qs = (p: Record<string, string | number | null | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
};

export const exportUrl = (slug: string, kind: "reviews" | "findings" | "usage" | "audit", format: "csv" | "json", days: number) =>
  apiUrl(`${o(slug)}/export/${kind}${qs({ format, days })}`);

export const p8 = {
  metrics: (s: string, days: number, repoId?: string) =>
    apiFetch<P.Metrics>(`${o(s)}/analytics/metrics${qs({ days, repo_id: repoId })}`),
  usage: (s: string, days: number) => apiFetch<P.Usage>(`${o(s)}/analytics/usage${qs({ days })}`),
  reports: (s: string) => apiFetch<P.ReportDefList>(`${o(s)}/reports`),
  createReport: (s: string, body: P.ReportDefIn) => apiFetch<P.ReportDef>(`${o(s)}/reports`, { method: "POST", body }),
  updateReport: (s: string, id: string, body: P.ReportDefIn) =>
    apiFetch<P.ReportDef>(`${o(s)}/reports/${seg(id)}`, { method: "PUT", body }),
  deleteReport: (s: string, id: string) => apiFetch<void>(`${o(s)}/reports/${seg(id)}`, { method: "DELETE" }),
  runReport: (s: string, id: string) => apiFetch<P.ReportRunSummary>(`${o(s)}/reports/${seg(id)}/run`, { method: "POST" }),
  customReport: (s: string, body: P.CustomReportIn) =>
    apiFetch<P.ReportRunSummary>(`${o(s)}/reports/custom`, { method: "POST", body }),
  reportRuns: (s: string) => apiFetch<P.ReportRunList>(`${o(s)}/report-runs?limit=50`),
  reportRun: (s: string, id: string) => apiFetch<P.ReportRunDetail>(`${o(s)}/report-runs/${seg(id)}`),
  apiKeys: (s: string) => apiFetch<P.ApiKeyList>(`${o(s)}/api-keys`),
  createApiKey: (s: string, name: string, expiresInDays: number | null) =>
    apiFetch<P.ApiKeyCreated>(`${o(s)}/api-keys`, { method: "POST", body: { name, expires_in_days: expiresInDays } }),
  revokeApiKey: (s: string, id: string) => apiFetch<void>(`${o(s)}/api-keys/${seg(id)}`, { method: "DELETE" }),
  auditLogs: (s: string, before?: string | null, action?: string) =>
    apiFetch<P.AuditList>(`${o(s)}/audit-logs${qs({ limit: 50, before, action })}`),
  pulls: (s: string, state: string) => apiFetch<{ pulls: P.CsPull[] }>(`${o(s)}/change-stack${qs({ state })}`),
  workspace: (s: string, pr: string, sha?: string | null) =>
    apiFetch<P.CsWorkspace>(`${o(s)}/change-stack/${seg(pr)}${qs({ sha })}`),
  file: (s: string, pr: string, f: { path: string; sha?: string; old_path?: string | null; status?: string }) =>
    apiFetch<P.CsFileContents>(`${o(s)}/change-stack/${seg(pr)}/file${qs(f)}`),
  chat: (s: string, pr: string) => apiFetch<{ messages: P.CsMessage[] }>(`${o(s)}/change-stack/${seg(pr)}/chat`),
  ask: (s: string, pr: string, body: { body: string; path?: string | null; line?: number | null; head_sha?: string | null }) =>
    apiFetch<{ messages: P.CsMessage[] }>(`${o(s)}/change-stack/${seg(pr)}/chat`, { method: "POST", body }),
  submitReview: (s: string, pr: string, body: P.CsReviewIn) =>
    apiFetch<{ review_ref: string; event: string }>(`${o(s)}/change-stack/${seg(pr)}/review`, { method: "POST", body }),
  merge: (s: string, pr: string, body: { method: P.MergeMethod; head_sha: string; commit_title?: string | null }) =>
    apiFetch<P.CsMergeOut>(`${o(s)}/change-stack/${seg(pr)}/merge`, { method: "POST", body }),
};

export const qk8 = {
  metrics: (s: string, d: number, r?: string) => ["org", s, "analytics", "metrics", d, r ?? ""] as const,
  usage: (s: string, d: number) => ["org", s, "analytics", "usage", d] as const,
  reports: (s: string) => ["org", s, "reports"] as const,
  runs: (s: string) => ["org", s, "report-runs"] as const,
  run: (s: string, id: string) => ["org", s, "report-runs", id] as const,
  apiKeys: (s: string) => ["org", s, "api-keys"] as const,
  audit: (s: string, a: string) => ["org", s, "audit", a] as const,
  pulls: (s: string, st: string) => ["org", s, "change-stack", "list", st] as const,
  workspace: (s: string, pr: string, sha: string | null) => ["org", s, "change-stack", pr, sha ?? "latest"] as const,
  file: (s: string, pr: string, sha: string, path: string) => ["org", s, "change-stack", pr, "file", sha, path] as const,
  chat: (s: string, pr: string) => ["org", s, "change-stack", pr, "chat"] as const,
};

export const useMetrics = (s: string, d: number, r?: string) =>
  useQuery({ queryKey: qk8.metrics(s, d, r), queryFn: () => p8.metrics(s, d, r) });
export const useUsage = (s: string, d: number) => useQuery({ queryKey: qk8.usage(s, d), queryFn: () => p8.usage(s, d) });
export const useReports = (s: string) => useQuery({ queryKey: qk8.reports(s), queryFn: () => p8.reports(s) });
export const useReportRuns = (s: string) =>
  useQuery({
    queryKey: qk8.runs(s),
    queryFn: () => p8.reportRuns(s),
    refetchInterval: (q) => (q.state.data?.runs.some((r) => r.status === "queued" || r.status === "running") ? 4000 : false),
  });
export const useReportRun = (s: string, id: string | null) =>
  useQuery({ queryKey: qk8.run(s, id ?? ""), queryFn: () => p8.reportRun(s, id ?? ""), enabled: !!id });
export const useApiKeys = (s: string, enabled: boolean) =>
  useQuery({ queryKey: qk8.apiKeys(s), queryFn: () => p8.apiKeys(s), enabled });
export const useAuditLogs = (s: string, action: string, enabled: boolean) =>
  useQuery({ queryKey: qk8.audit(s, action), queryFn: () => p8.auditLogs(s, null, action || undefined), enabled });
export const usePulls = (s: string, state: string) =>
  useQuery({ queryKey: qk8.pulls(s, state), queryFn: () => p8.pulls(s, state) });
export const useWorkspace = (s: string, pr: string, sha: string | null) =>
  useQuery({ queryKey: qk8.workspace(s, pr, sha), queryFn: () => p8.workspace(s, pr, sha) });
export const useCsFile = (s: string, pr: string, sha: string, f: P.CsFile | null) =>
  useQuery({
    queryKey: qk8.file(s, pr, sha, f?.path ?? ""),
    queryFn: () => p8.file(s, pr, { path: f!.path, sha, old_path: f!.old_path, status: f!.status }),
    enabled: !!f,
    staleTime: Infinity,
  });
export const useCsChat = (s: string, pr: string) =>
  useQuery({
    queryKey: qk8.chat(s, pr),
    queryFn: () => p8.chat(s, pr),
    refetchInterval: (q) =>
      q.state.data?.messages.some((m) => m.status === "queued" || m.status === "running") ? 3000 : false,
  });
