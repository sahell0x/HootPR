import type { Page, Route } from "@playwright/test";
import { configSchema } from "../fixtures/config-schema";

export const org = { id: "o1", slug: "acme", provider: "github", kind: "org", name: "acme", avatar_url: null,
  role: "admin", credits_balance: "300.00", installed: true, knowledge_base_opt_out: false };
export const me = { id: "u1", email: "a@example.com", display_name: "Alice", avatar_url: null, csrf_token: "t",
  identities: [{ provider: "github", provider_user_id: "501", username: "alice" }] };
export const billing = { balance: "300.00", purchases_count: 0, max_purchases: 1, max_balance: "500.00",
  pack: { credits: 200, price_paise: 9900, currency: "INR" }, can_purchase: true, purchase_blocked_reason: null,
  ledger: [{ id: "l1", delta: "300.00", reason: "signup_bonus", ref_type: "organization", ref_id: "o1",
    balance_after: "300.00", created_at: "2026-09-28T09:00:00Z" }], disclaimer: "x", test_mode: true };

export const meta = { github_app_slug: "hootpr", github_install_url: "https://github.com/apps/hootpr/installations/new",
  gitlab_base_url: "https://gitlab.com", razorpay_key_id: "rzp_test_x", billing_test_mode: true, disclaimer: "x",
  credit_pack: { credits: 200, price_paise: 9900, currency: "INR" },
  credit_prices: { per_review: "100", per_chat_reply: "50", signup_bonus: "300" },
  providers_enabled: { github: true, gitlab: true } };

type Handler = (route: Route) => Promise<void> | void;

export async function mockApi(page: Page, overrides: Record<string, Handler> = {}) {
  await page.context().addCookies([{ name: "hootpr_csrf", value: "t", url: "http://127.0.0.1" }]);
  const defaults: Record<string, unknown> = {
    "GET /api/meta": meta,
    "GET /api/me": me,
    "GET /api/orgs": { orgs: [org] },
    "GET /api/orgs/acme": org,
    "GET /api/orgs/acme/repos": { repos: [{ id: "r1", provider: "github", full_name: "acme/web", private: true,
      enabled: true, default_branch: "main", last_review_at: null }], can_install: true, install_url: "https://github.com/apps/hootpr/installations/new" },
    "GET /api/orgs/acme/billing": billing,
    "GET /api/orgs/acme/learnings": { learnings: [], next_before: null },
    "GET /api/schema/hootpr.v1.json": configSchema,
    "GET /api/orgs/acme/repos/r1/effective-config": { config: {}, provenance: {},
      yaml: "# Effective HootPR configuration (source: defaults)\nlanguage: en-US\n",
      sources: ["default"], yaml_file_note: "A .hootpr.yaml on the default branch overrides these settings." },
    "GET /api/orgs/acme/repos/r1/settings": { repo: { id: "r1", provider: "github", full_name: "acme/web",
      private: true, enabled: true, default_branch: "main", last_review_at: null }, settings: {} },
  };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    const override = overrides[key];
    if (override) return override(route);
    if (key in defaults) return route.fulfill({ json: defaults[key] });
    return route.fulfill({ status: 404, json: { detail: { code: "not_found", message: key } } });
  });
}
