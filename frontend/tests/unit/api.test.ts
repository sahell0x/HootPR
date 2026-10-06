import { describe, expect, test, vi } from "vitest";
import { api, ApiError, apiFetch, loginUrl, setCsrfToken } from "@/lib/api";
import { jsonResponse } from "../utils";

describe("apiFetch", () => {
  test("GET sends no csrf header and returns json", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/api/meta")).resolves.toEqual({ ok: 1 });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(init.credentials).toBe("include");
  });

  test("mutations send the csrf cookie value", async () => {
    document.cookie = "hootpr_csrf=tok123; path=/";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(null, 204));
    vi.stubGlobal("fetch", fetchMock);
    await api.logout();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/auth/logout");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
  });

  test("application errors become ApiError with code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: { code: "purchase_cap_reached", message: "Max 2 packs" } }, 409),
      ),
    );
    const err = await api.createOrder("acme").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("purchase_cap_reached");
    expect((err as ApiError).message).toBe("Max 2 packs");
    expect((err as ApiError).status).toBe(409);
  });

  test("invalid_settings errors carry the error list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: {
              code: "invalid_settings",
              message: "Settings are invalid",
              errors: [{ line: null, path: "reviews.profile", message: "bad" }],
            },
          },
          422,
        ),
      ),
    );
    const err = (await api.putOrgSettings("acme", { settings: {} }).catch((e: unknown) => e)) as ApiError;
    expect(err.errors?.[0]?.path).toBe("reviews.profile");
  });

  test("FastAPI validation errors are flattened", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: [{ loc: ["body", "role"], msg: "Input should be 'admin'", type: "enum" }] }, 422),
      ),
    );
    const err = (await api.updateMemberRole("acme", "u1", "admin").catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("validation_error");
    expect(err.message).toContain("role");
  });

  test("non-json error bodies still produce an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad gateway", { status: 502 })));
    const err = (await api.me().catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    expect(err.code).toBe("http_error");
  });

  test("reviews builds the cursor query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ reviews: [], next_before: null }));
    vi.stubGlobal("fetch", fetchMock);
    await api.reviews("acme", { before: "2026-09-01T00:00:00Z", limit: 20 });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/orgs/acme/reviews?limit=20&before=2026-09-01T00%3A00%3A00Z",
    );
  });

  test("uses the runtime API base URL from window.__HOOTPR__", async () => {
    window.__HOOTPR__ = { apiUrl: "https://api.example.com/" };
    try {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }));
      vi.stubGlobal("fetch", fetchMock);
      await apiFetch("/api/meta");
      expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example.com/api/meta");
      expect(loginUrl("github", "/orgs")).toBe("https://api.example.com/api/auth/github/login?next=%2Forgs");
    } finally {
      delete window.__HOOTPR__;
    }
  });

  test("on csrf_failed the token is fetched from /api/auth/csrf, the call retried and the token kept", async () => {
    setCsrfToken(null);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "csrf_failed", message: "x" } }, 403))
      .mockResolvedValueOnce(jsonResponse({ csrf_token: "fromapi" }))
      .mockImplementation(async () => jsonResponse(null, 204));
    vi.stubGlobal("fetch", fetchMock);
    await api.logout();
    await api.logout();
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map((c) => c[0])).toEqual(["/api/auth/logout", "/api/auth/csrf", "/api/auth/logout", "/api/auth/logout"]);
    expect(calls[1]?.[1].credentials).toBe("include");
    expect((calls[2]?.[1].headers as Record<string, string>)["X-CSRF-Token"]).toBe("fromapi");
    expect((calls[3]?.[1].headers as Record<string, string>)["X-CSRF-Token"]).toBe("fromapi");
    setCsrfToken(null);
  });

  test("/api/me's csrf_token is remembered for mutations", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "u", csrf_token: "frome", identities: [] }))
      .mockResolvedValue(jsonResponse(null, 204));
    vi.stubGlobal("fetch", fetchMock);
    await api.me();
    await api.logout();
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("frome");
    setCsrfToken(null);
  });

  test("loginUrl", () => {
    expect(loginUrl("github")).toBe("/api/auth/github/login");
    expect(loginUrl("gitlab", "/o/x/repos")).toBe("/api/auth/gitlab/login?next=%2Fo%2Fx%2Frepos");
  });
});

test("llmCall fetches the call detail under the review", async () => {
  const fetchMock = vi.fn(async () => jsonResponse({ id: "c1", request_excerpt: "REQ", response_excerpt: "RESP" }));
  vi.stubGlobal("fetch", fetchMock);
  const out = await api.llmCall("acme", "rev1", "c1");
  expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe("/api/orgs/acme/reviews/rev1/llm-calls/c1");
  expect(out.request_excerpt).toBe("REQ");
});

test("learnings client builds query strings and bodies", async () => {
  const fetchMock = vi.fn(async () => jsonResponse({ learnings: [], next_before: null }));
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "hootpr_csrf=t";
  await api.learnings("acme", { repoId: "r1", q: "print", before: "2026-09-29T10:00:00Z", limit: 20 });
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
  expect(calls[0]?.[0]).toBe("/api/orgs/acme/learnings?limit=20&repo_id=r1&q=print&before=2026-09-29T10%3A00%3A00Z");
  await api.learnings("acme");
  expect(calls[1]?.[0]).toBe("/api/orgs/acme/learnings?limit=50");
  await api.createLearning("acme", { text: "Use logging.", scope: "org", repo_id: null, path_glob: null });
  expect(calls[2]?.[1]).toMatchObject({
    method: "POST",
    body: JSON.stringify({ text: "Use logging.", scope: "org", repo_id: null, path_glob: null }),
  });
  await api.updateLearning("acme", "l1", { text: "x" });
  expect(calls[3]?.[0]).toBe("/api/orgs/acme/learnings/l1");
  expect(calls[3]?.[1]).toMatchObject({ method: "PATCH", body: JSON.stringify({ text: "x" }) });
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
  await api.deleteLearning("acme", "l1");
  expect(calls[4]?.[1]).toMatchObject({ method: "DELETE" });
  await api.effectiveConfig("acme", "r1");
  expect(calls[5]?.[0]).toBe("/api/orgs/acme/repos/r1/effective-config");
  await api.configSchema();
  expect(calls[6]?.[0]).toBe("/api/schema/hootpr.v1.json");
});
