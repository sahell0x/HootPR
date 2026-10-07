import type * as T from "./api-types";
import { clearAuthStorage, setAuthHint } from "./auth-storage";
import { apiUrl } from "./runtime-config";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public errors?: T.ConfigError[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null;
}

interface ValidationItem {
  loc?: (string | number)[];
  msg?: string;
}

export function toApiError(status: number, data: unknown): ApiError {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) {
    const msg = (detail as ValidationItem[])
      .map((d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
      .join("; ");
    return new ApiError(status, "validation_error", msg);
  }
  if (detail && typeof detail === "object") {
    const d = detail as { code?: string; message?: string; errors?: T.ConfigError[] };
    return new ApiError(status, d.code ?? "http_error", d.message ?? `HTTP ${status}`, d.errors);
  }
  return new ApiError(status, "http_error", typeof detail === "string" ? detail : `HTTP ${status}`);
}

// The API is a separate origin, so its CSRF cookie is not readable here: the token comes in the body
// of /api/me or /api/auth/csrf and is kept in memory (the cookie is a fallback for same-host setups).
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

async function fetchCsrf(): Promise<string | null> {
  try {
    const res = await fetch(apiUrl("/api/auth/csrf"), { credentials: "include", headers: { Accept: "application/json" } });
    const data = (await res.json().catch(() => null)) as { csrf_token?: string } | null;
    csrfToken = res.ok && data?.csrf_token ? data.csrf_token : null;
  } catch {
    csrfToken = null;
  }
  return csrfToken;
}

const isCsrfFailure = (status: number, data: unknown) =>
  status === 403 && (data as { detail?: { code?: string } } | null)?.detail?.code === "csrf_failed";

export async function apiFetch<R>(path: string, init: { method?: string; body?: unknown } = {}): Promise<R> {
  const method = init.method ?? "GET";
  const mutating = method !== "GET" && method !== "HEAD";
  const send = (token: string | null) => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    if (mutating && token) headers["X-CSRF-Token"] = token;
    return fetch(apiUrl(path), {
      method,
      headers,
      credentials: "include",
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  };
  const read = async (r: Response): Promise<unknown> => (r.status === 204 ? null : r.json().catch(() => null));
  let res = await send(mutating ? (csrfToken ?? readCookie("hootpr_csrf")) : null);
  let data = await read(res);
  if (mutating && isCsrfFailure(res.status, data)) {
    // No token yet (or a stale one, e.g. rotated by a sign-in in another tab): fetch it and retry once.
    res = await send(await fetchCsrf());
    data = await read(res);
  }
  if (res.status === 204) return undefined as R;
  if (!res.ok) {
    if (res.status === 401 && path === "/api/me") setAuthHint(false);
    throw toApiError(res.status, data);
  }
  if (path === "/api/me") {
    setCsrfToken((data as { csrf_token?: string } | null)?.csrf_token ?? csrfToken);
    setAuthHint(true);
  }
  return data as R;
}

/** Absolute API URL for links the browser navigates to (OAuth, downloads). */
export { apiUrl } from "./runtime-config";

export const loginUrl = (provider: T.Provider, next?: string) =>
  apiUrl(`/api/auth/${provider}/login${next ? `?next=${encodeURIComponent(next)}` : ""}`);

const o = (slug: string) => `/api/orgs/${encodeURIComponent(slug)}`;
const seg = (s: string) => encodeURIComponent(s);

export const api = {
  me: () => apiFetch<T.Me>("/api/me"),
  meta: () => apiFetch<T.Meta>("/api/meta"),
  logout: async () => {
    try {
      await apiFetch<void>("/api/auth/logout", { method: "POST" });
    } finally {
      clearAuthStorage();
    }
  },
  orgCandidates: () => apiFetch<T.OrgCandidateList>("/api/orgs/candidates"),
  orgs: () => apiFetch<T.OrgList>("/api/orgs"),
  selectOrg: (body: T.SelectOrgRequest) => apiFetch<T.Org>("/api/orgs/select", { method: "POST", body }),
  org: (slug: string) => apiFetch<T.Org>(o(slug)),
  orgSettings: (slug: string) => apiFetch<T.OrgSettings>(`${o(slug)}/settings`),
  putOrgSettings: (slug: string, body: T.SettingsUpdate) =>
    apiFetch<T.OrgSettings>(`${o(slug)}/settings`, { method: "PUT", body }),
  members: (slug: string) => apiFetch<T.MemberList>(`${o(slug)}/members`),
  updateMemberRole: (slug: string, userId: string, role: T.Role) =>
    apiFetch<T.Member>(`${o(slug)}/members/${seg(userId)}`, {
      method: "PATCH",
      body: { role } satisfies T.RoleUpdate,
    }),
  repos: (slug: string) => apiFetch<T.RepoList>(`${o(slug)}/repos`),
  updateRepo: (slug: string, repoId: string, body: T.UpdateRepoRequest) =>
    apiFetch<T.Repo>(`${o(slug)}/repos/${seg(repoId)}`, { method: "PATCH", body }),
  repoSettings: (slug: string, repoId: string) =>
    apiFetch<T.RepoSettings>(`${o(slug)}/repos/${seg(repoId)}/settings`),
  putRepoSettings: (slug: string, repoId: string, body: T.SettingsUpdate) =>
    apiFetch<T.RepoSettings>(`${o(slug)}/repos/${seg(repoId)}/settings`, { method: "PUT", body }),
  syncRepos: (slug: string) => apiFetch<{ status: string }>(`${o(slug)}/repos/sync`, { method: "POST" }),
  gitlabBot: (slug: string) => apiFetch<T.GitlabBot>(`${o(slug)}/gitlab/bot`),
  putGitlabBot: (slug: string, body: T.GitlabBotRequest) =>
    apiFetch<T.GitlabBot>(`${o(slug)}/gitlab/bot`, { method: "PUT", body }),
  deleteGitlabBot: (slug: string) => apiFetch<void>(`${o(slug)}/gitlab/bot`, { method: "DELETE" }),
  gitlabProjects: (slug: string) => apiFetch<T.GitlabProjectList>(`${o(slug)}/gitlab/projects`),
  putGitlabProjects: (slug: string, body: T.GitlabProjectsRequest) =>
    apiFetch<T.RepoList>(`${o(slug)}/gitlab/projects`, { method: "PUT", body }),
  reviews: (slug: string, p: { limit?: number; before?: string | null; repoId?: string } = {}) => {
    const q = new URLSearchParams();
    q.set("limit", String(p.limit ?? 50));
    if (p.before) q.set("before", p.before);
    if (p.repoId) q.set("repo_id", p.repoId);
    return apiFetch<T.ReviewList>(`${o(slug)}/reviews?${q.toString()}`);
  },
  review: (slug: string, id: string) => apiFetch<T.ReviewDetail>(`${o(slug)}/reviews/${seg(id)}`),
  llmCall: (slug: string, reviewId: string, callId: string) =>
    apiFetch<T.LlmCallDetail>(`${o(slug)}/reviews/${seg(reviewId)}/llm-calls/${seg(callId)}`),
  billing: (slug: string) => apiFetch<T.Billing>(`${o(slug)}/billing`),
  receipt: (slug: string, refType: string, refId: string) =>
    apiFetch<T.CreditReceipt>(`${o(slug)}/billing/receipts/${seg(refType)}/${seg(refId)}`),
  createOrder: (slug: string) => apiFetch<T.Order>(`${o(slug)}/billing/orders`, { method: "POST" }),
  cancelOrder: (slug: string, orderId: string) =>
    apiFetch<void>(`${o(slug)}/billing/orders/${seg(orderId)}/cancel`, { method: "POST" }),
  verifyPayment: (body: T.VerifyPaymentRequest) =>
    apiFetch<T.VerifyResult>("/api/billing/verify", { method: "POST", body }),
  learnings: (slug: string, p: { repoId?: string; q?: string; before?: string | null; limit?: number } = {}) => {
    const q = new URLSearchParams();
    q.set("limit", String(p.limit ?? 50));
    if (p.repoId) q.set("repo_id", p.repoId);
    if (p.q) q.set("q", p.q);
    if (p.before) q.set("before", p.before);
    return apiFetch<T.LearningList>(`${o(slug)}/learnings?${q.toString()}`);
  },
  createLearning: (slug: string, body: T.LearningCreate) =>
    apiFetch<T.Learning>(`${o(slug)}/learnings`, { method: "POST", body }),
  updateLearning: (slug: string, id: string, body: T.LearningUpdate) =>
    apiFetch<T.Learning>(`${o(slug)}/learnings/${seg(id)}`, { method: "PATCH", body }),
  deleteLearning: (slug: string, id: string) =>
    apiFetch<void>(`${o(slug)}/learnings/${seg(id)}`, { method: "DELETE" }),
  effectiveConfig: (slug: string, repoId: string) =>
    apiFetch<T.EffectiveConfig>(`${o(slug)}/repos/${seg(repoId)}/effective-config`),
  configSchema: () => apiFetch<T.ConfigSchema>("/api/schema/hootpr.v1.json"),
  validateConfig: (yaml: string) =>
    apiFetch<T.ConfigValidation>("/api/config/validate", {
      method: "POST",
      body: { yaml } satisfies T.ValidateConfigRequest,
    }),
};
