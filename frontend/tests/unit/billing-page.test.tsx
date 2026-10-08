import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import BillingPage from "@/app/o/[org]/billing/page";
import { jsonResponse, renderWithQuery } from "../utils";

const orgBody = (role: string) => ({ id: "o1", slug: "acme", provider: "github", kind: "org", name: "acme",
  avatar_url: null, role, credits_balance: "200.00", installed: true, knowledge_base_opt_out: false });
const billing = { balance: "200.00", purchases_count: 0, max_purchases: 1, max_balance: "500.00",
  pack: { credits: 200, price_paise: 9900, currency: "INR" }, can_purchase: true, purchase_blocked_reason: null,
  disclaimer: "d", test_mode: true, ledger: [
    { id: "l2", delta: "-100.00", reason: "review_hold", ref_type: "review", ref_id: "x", balance_after: "200.00", created_at: "2026-09-28T10:00:00Z" },
    { id: "l1", delta: "300.00", reason: "signup_bonus", ref_type: "organization", ref_id: "o1", balance_after: "300.00", created_at: "2026-09-28T09:00:00Z" }] };

test("shows balance, caps and ledger without a site-wide test-mode notice", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme" ? jsonResponse(orgBody("member")) : jsonResponse(billing)));
  renderWithQuery(<BillingPage />);
  expect(await screen.findByText("0 / 1 pack bought")).toBeInTheDocument();
  expect(screen.getByText("Signup bonus")).toBeInTheDocument();
  expect(screen.getByText("+300")).toBeInTheDocument();
  expect(screen.getByText("-100")).toBeInTheDocument();
  expect(screen.queryByText(/no real money/i)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /buy 200 credits/i })).toBeDisabled();
  expect(screen.getByText(/only admins and billing admins/i)).toBeInTheDocument();
});

const metering = { review_min_charge: "10.00", review_hold_max: "500.00", chat_min_charge: "5.00",
  avg_review_credits_30d: "112", reviews_30d: 14 };

test("explains metering with the org's 30-day average and no flat per-review price", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/orgs/acme") return jsonResponse(orgBody("admin"));
    if (url === "/api/meta")
      return jsonResponse({ credit_prices: { per_review: "200", per_chat_reply: "100", signup_bonus: "300" },
        providers_enabled: { github: true, gitlab: true } });
    return jsonResponse({ ...billing, metering });
  }));
  renderWithQuery(<BillingPage />);
  const section = await screen.findByRole("region", { name: "How credits are metered" });
  expect(section).toHaveTextContent(/reserves credits up front based on the pull request's size, up to 500 credits/);
  expect(section).toHaveTextContent(/minimum of 10 credits per review/);
  expect(section).toHaveTextContent(/returns|goes back to your balance instantly/);
  expect(screen.getByTestId("metering-average")).toHaveTextContent("Average review: 112 credits (last 30 days, 14 reviews)");
  expect(screen.queryByText(/1 review =/)).not.toBeInTheDocument();
  expect(screen.queryByText(/chat reply =/)).not.toBeInTheDocument();
  expect(screen.getAllByText(/billed by actual AI usage/i).length).toBeGreaterThan(0);
});

test("without metering data or recent reviews the section falls back to typical-review copy", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme" ? jsonResponse(orgBody("admin"))
      : jsonResponse({ ...billing, metering: { ...metering, avg_review_credits_30d: null, reviews_30d: 0 } })));
  renderWithQuery(<BillingPage />);
  expect(await screen.findByTestId("metering-average")).toHaveTextContent("a typical review is about 100 credits");
});

test("ledger labels metered reasons, describes rows and links them via href", async () => {
  const ledger = [
    { id: "l4", delta: "20.00", reason: "review", ref_type: "review", ref_id: "rev9", balance_after: "1415",
      created_at: "2026-09-28T12:00:00Z", charged: "280.00", description: "acme/web #12 · Fix login",
      href: "/o/acme/reviews/rev9", has_receipt: true },
    { id: "l3", delta: "-300.00", reason: "review_hold", ref_type: "review", ref_id: "rev9", balance_after: "1395",
      created_at: "2026-09-28T11:00:00Z", charged: null, description: "acme/web #12 · Fix login",
      href: "/o/acme/reviews/rev9", has_receipt: true },
    { id: "l2", delta: "-12", reason: "chat", ref_type: "chat", ref_id: "c1", balance_after: "1695",
      created_at: "2026-09-28T10:30:00Z", charged: null, description: "Chat reply on acme/web #12", href: null, has_receipt: true },
    { id: "l1", delta: "300", reason: "signup_bonus", ref_type: "organization", ref_id: "o1", balance_after: "1707",
      created_at: "2026-09-28T10:00:00Z", charged: null, description: null, href: null, has_receipt: false },
  ];
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme" ? jsonResponse(orgBody("admin")) : jsonResponse({ ...billing, ledger, metering })));
  renderWithQuery(<BillingPage />);
  expect(await screen.findByText("Review settled")).toBeInTheDocument();
  expect(screen.getByText("Reserved for review")).toBeInTheDocument();
  expect(screen.getByText("charged 280 — returned 20")).toBeInTheDocument();
  const links = screen.getAllByRole("link", { name: /acme\/web #12 · Fix login/ });
  expect(links).toHaveLength(2);
  links.forEach((l) => expect(l).toHaveAttribute("href", "/o/acme/reviews/rev9"));
  expect(screen.getByText("Chat reply on acme/web #12")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /chat reply/i })).not.toBeInTheDocument();
  // receipt chevrons on the three metered rows, none on the signup bonus
  expect(screen.getAllByRole("button", { name: "Show credit receipt" })).toHaveLength(3);
  expect(screen.queryByTestId("owner-usage")).not.toBeInTheDocument();
});

test("hold and settle rows are labelled by the job they belong to, not always 'review'", async () => {
  const row = (id: string, reason: string, ref_type: string, delta: string) => ({ id, delta, reason, ref_type, ref_id: id,
    balance_after: "500", created_at: "2026-09-28T10:00:00Z", charged: null, description: null, href: null, has_receipt: false });
  const ledger = [row("a", "review", "finishing", "0"), row("b", "review_hold", "finishing", "-100"),
    row("c", "review_hold", "security_scan", "-500"), row("d", "chat", "chat", "45")];
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme" ? jsonResponse(orgBody("admin")) : jsonResponse({ ...billing, ledger, metering })));
  renderWithQuery(<BillingPage />);
  expect(await screen.findByText("Finishing touch settled")).toBeInTheDocument();
  expect(screen.getByText("Reserved for finishing touch")).toBeInTheDocument();
  expect(screen.getByText("Reserved for security review")).toBeInTheDocument();
  expect(screen.getByText("Chat reply settled")).toBeInTheDocument();
  expect(screen.queryByText("Review settled")).not.toBeInTheDocument();
});

test("expanding a ledger row lazily loads and renders its credit receipt", async () => {
  const ledger = [{ id: "l2", delta: "92", reason: "chat", ref_type: "chat", ref_id: "c1", balance_after: "1695",
    created_at: "2026-09-28T10:30:00Z", charged: "8", description: "Chat reply on acme/web #12", href: null, has_receipt: true }];
  const receipt = { reserved: "100", charged: "8", refunded: "92", minimum_applied: false, budget_reached: false, legacy: false,
    lines: [{ stage: "chat", label: "Chat reply", credits: "8", input_tokens: null, cached_tokens: null, output_tokens: null, cost_usd: null }] };
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/orgs/acme") return jsonResponse(orgBody("admin"));
    if (url === "/api/orgs/acme/billing/receipts/chat/c1") return jsonResponse(receipt);
    return jsonResponse({ ...billing, ledger, metering });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<BillingPage />);
  const toggle = await screen.findByRole("button", { name: "Show credit receipt" });
  expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/receipts/"))).toBe(false);
  await userEvent.click(toggle);
  const card = await screen.findByTestId("credit-receipt");
  expect(within(card).getByTestId("receipt-charged")).toHaveTextContent("8");
  expect(within(card).getByText("Reserved 100 · Returned 92")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Hide credit receipt" })).toHaveAttribute("aria-expanded", "true");
});

test("platform owners see the owner-only unbilled usage card", async () => {
  const usage_30d = { billed_credits: "880", unbilled_credits: "30", charged_credits: "1000", cost_usd: "0.500000",
    by_source: [{ source: "post_merge", credits: "20", cost_usd: "0.010000" }, { source: "reports", credits: "10", cost_usd: null }] };
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme" ? jsonResponse(orgBody("admin")) : jsonResponse({ ...billing, metering, usage_30d })));
  renderWithQuery(<BillingPage />);
  const card = within(await screen.findByTestId("owner-usage"));
  expect(card.getByText("Owner only")).toBeInTheDocument();
  expect(card.getByText("880")).toBeInTheDocument();
  expect(card.getByText("30")).toBeInTheDocument();
  expect(card.getByText("$0.5000")).toBeInTheDocument();
  expect(card.getByText("$0.0500 per 100 credits charged")).toBeInTheDocument();
  expect(card.getByText("post merge")).toBeInTheDocument();
});

test("a failed billing request shows the error instead of an endless skeleton", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme"
      ? jsonResponse(orgBody("admin"))
      : jsonResponse({ detail: { code: "internal", message: "Billing is down" } }, 500)));
  renderWithQuery(<BillingPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Billing is down");
});

test("an expired session on billing redirects to sign in", async () => {
  const { useRouter } = await import("next/navigation");
  vi.stubGlobal("fetch", vi.fn(async () =>
    jsonResponse({ detail: { code: "unauthenticated", message: "Sign in required" } }, 401)));
  renderWithQuery(<BillingPage />);
  await waitFor(() =>
    expect(useRouter().replace).toHaveBeenCalledWith(`/login?next=${encodeURIComponent("/o/acme/repos")}`));
});
