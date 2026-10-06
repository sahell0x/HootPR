"use client";
// Phase 6 (security suite) API types + hooks. Scan rows alias the generated OpenAPI schema; the
// surface map / report / stats JSON blobs (free-form dicts server-side) are typed here.
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api";
import type { components } from "./openapi";

type S = components["schemas"];

export type ScanKind = S["ScanSummary"]["kind"];
export type ScanStatus = S["ScanSummary"]["status"];
export type RiskLevel = "critical" | "high" | "medium" | "low";

export interface SurfaceStats {
  source_files?: number;
  parsed_files?: number;
  entry_points?: number;
  http_endpoints?: number;
  unauthenticated_endpoints?: number;
  outbound_calls?: number;
  secrets?: number;
  iac_findings?: number;
  languages?: Record<string, number>;
}

export type ScanSummary = Omit<S["ScanSummary"], "stats" | "overall_risk"> & {
  stats: SurfaceStats;
  overall_risk: RiskLevel | null;
};

export interface SurfaceEntryPoint {
  kind: "http" | "cli" | "message" | "server_action";
  framework: string;
  method: string | null;
  route: string | null;
  name: string;
  path: string;
  line: number;
  auth: boolean;
  auth_evidence: string | null;
  handler?: string;
}

export interface SurfaceMap {
  version: number;
  truncated: boolean;
  stats: SurfaceStats;
  entry_points: SurfaceEntryPoint[];
  outbound: { callee: string; path: string; line: number; symbol: string }[];
  sinks: { counts: Record<string, number>; examples: Record<string, { callee: string; path: string; line: number }[]> };
  secrets: { name: string; path: string; line: number; source: string }[];
  iac: { kind: string; rule: string; path: string; line: number; detail: string }[];
}

export interface SecurityRisk {
  title: string;
  severity: RiskLevel;
  category: string;
  description: string;
  affected: string[];
  recommendation: string;
}

export interface SecurityReport {
  summary: string;
  overall_risk: RiskLevel;
  risks: SecurityRisk[];
  strengths: string[];
}

export type ScanDetail = ScanSummary & {
  surface: SurfaceMap | null;
  report: SecurityReport | null;
};

export type RepoSecurity = Omit<
  S["RepoSecurity"],
  "latest_surface" | "latest_review" | "active" | "history"
> & {
  latest_surface: ScanSummary | null;
  latest_review: ScanSummary | null;
  active: ScanSummary[];
  history: ScanSummary[];
};

export type SecurityOverview = Omit<S["SecurityOverview"], "repos"> & { repos: RepoSecurity[] };

const o = (slug: string) => `/api/orgs/${encodeURIComponent(slug)}`;

export const securityApi = {
  overview: (slug: string) => apiFetch<SecurityOverview>(`${o(slug)}/security`),
  scan: (slug: string, id: string) =>
    apiFetch<ScanDetail>(`${o(slug)}/security/scans/${encodeURIComponent(id)}`),
  start: (slug: string, repoId: string, kind: ScanKind) =>
    apiFetch<ScanSummary>(`${o(slug)}/repos/${encodeURIComponent(repoId)}/security/scans`, {
      method: "POST",
      body: { kind },
    }),
};

export const securityKeys = {
  overview: (s: string) => ["org", s, "security"] as const,
  scan: (s: string, id: string) => ["org", s, "security", "scans", id] as const,
};

/** Polls every 5 s while any scan is queued/running. */
export const useSecurityOverview = (slug: string) =>
  useQuery({
    queryKey: securityKeys.overview(slug),
    queryFn: () => securityApi.overview(slug),
    refetchInterval: (q) => (q.state.data?.repos.some((r) => r.active.length > 0) ? 5000 : false),
  });

export const useSecurityScan = (slug: string, id: string | null) =>
  useQuery({
    queryKey: securityKeys.scan(slug, id ?? ""),
    queryFn: () => securityApi.scan(slug, id ?? ""),
    enabled: Boolean(id),
  });
