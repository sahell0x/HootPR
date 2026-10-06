"use client";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "./api";

export const qk = {
  me: ["me"] as const,
  meta: ["meta"] as const,
  candidates: ["orgs", "candidates"] as const,
  orgs: ["orgs"] as const,
  org: (s: string) => ["org", s] as const,
  repos: (s: string) => ["org", s, "repos"] as const,
  repoSettings: (s: string, id: string) => ["org", s, "repos", id, "settings"] as const,
  orgSettings: (s: string) => ["org", s, "settings"] as const,
  members: (s: string) => ["org", s, "members"] as const,
  gitlabBot: (s: string) => ["org", s, "gitlab", "bot"] as const,
  gitlabProjects: (s: string) => ["org", s, "gitlab", "projects"] as const,
  reviews: (s: string) => ["org", s, "reviews"] as const,
  review: (s: string, id: string) => ["org", s, "reviews", id] as const,
  llmCall: (s: string, r: string, c: string) => ["org", s, "reviews", r, "llm-calls", c] as const,
  billing: (s: string) => ["org", s, "billing"] as const,
  receipt: (s: string, refType: string, refId: string) => ["org", s, "billing", "receipts", refType, refId] as const,
  learningsAll: (s: string) => ["org", s, "learnings"] as const,
  learnings: (s: string, f: LearningFilters) => ["org", s, "learnings", f] as const,
  effectiveConfig: (s: string, id: string) => ["org", s, "repos", id, "effective-config"] as const,
  configSchema: ["config-schema"] as const,
};

export interface LearningFilters {
  repoId?: string;
  q?: string;
}

export const useMe = () => useQuery({ queryKey: qk.me, queryFn: api.me, retry: false });
export const useMeta = () => useQuery({ queryKey: qk.meta, queryFn: api.meta, staleTime: Infinity });
export const useOrgCandidates = () =>
  useQuery({ queryKey: qk.candidates, queryFn: api.orgCandidates, retry: false });
export const useOrgs = () => useQuery({ queryKey: qk.orgs, queryFn: api.orgs });
export const useOrg = (s: string) => useQuery({ queryKey: qk.org(s), queryFn: () => api.org(s), retry: false });
export const useRepos = (s: string) => useQuery({ queryKey: qk.repos(s), queryFn: () => api.repos(s) });
export const useRepoSettings = (s: string, id: string) =>
  useQuery({ queryKey: qk.repoSettings(s, id), queryFn: () => api.repoSettings(s, id) });
export const useOrgSettings = (s: string) =>
  useQuery({ queryKey: qk.orgSettings(s), queryFn: () => api.orgSettings(s) });
export const useMembers = (s: string) => useQuery({ queryKey: qk.members(s), queryFn: () => api.members(s) });
export const useGitlabBot = (s: string, enabled = true) =>
  useQuery({ queryKey: qk.gitlabBot(s), queryFn: () => api.gitlabBot(s), enabled });
export const useGitlabProjects = (s: string, enabled: boolean) =>
  useQuery({ queryKey: qk.gitlabProjects(s), queryFn: () => api.gitlabProjects(s), enabled });
export const useReviews = (s: string) =>
  useInfiniteQuery({
    queryKey: qk.reviews(s),
    queryFn: ({ pageParam }) => api.reviews(s, { before: pageParam, limit: 50 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_before,
  });
export const useReview = (s: string, id: string) =>
  useQuery({ queryKey: qk.review(s, id), queryFn: () => api.review(s, id) });
/** One LLM call's request/response excerpts, fetched lazily when its trace row is expanded. */
export const useLlmCall = (s: string, reviewId: string, callId: string, enabled: boolean) =>
  useQuery({
    queryKey: qk.llmCall(s, reviewId, callId),
    queryFn: () => api.llmCall(s, reviewId, callId),
    enabled,
    staleTime: Infinity,
  });
export const useBilling = (s: string) => useQuery({ queryKey: qk.billing(s), queryFn: () => api.billing(s) });
/** One metered job's credit receipt (ledger rows with `has_receipt`); fetched only when `enabled`. */
export const useReceipt = (s: string, refType: string, refId: string, enabled = true) =>
  useQuery({ queryKey: qk.receipt(s, refType, refId), queryFn: () => api.receipt(s, refType, refId), enabled });
/** Learnings, newest first, paged on `next_before`; `qk.learningsAll(s)` invalidates every filter. */
export const useLearnings = (s: string, f: LearningFilters) =>
  useInfiniteQuery({
    queryKey: qk.learnings(s, f),
    queryFn: ({ pageParam }) => api.learnings(s, { ...f, before: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_before,
  });
export const useEffectiveConfig = (s: string, id: string) =>
  useQuery({ queryKey: qk.effectiveConfig(s, id), queryFn: () => api.effectiveConfig(s, id) });
export const useConfigSchema = () =>
  useQuery({ queryKey: qk.configSchema, queryFn: api.configSchema, staleTime: Infinity });
