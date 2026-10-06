import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { BuyCredits } from "@/components/buy-credits";
import type { Billing } from "@/lib/api-types";
import { jsonResponse, renderWithQuery } from "../utils";

const billing: Billing = { balance: "300.00", purchases_count: 0, max_purchases: 2, max_balance: "1000.00",
  pack: { credits: 500, price_paise: 4900, currency: "INR" }, can_purchase: true, purchase_blocked_reason: null,
  ledger: [], disclaimer: "…", test_mode: true };

test("buys a pack through checkout and verifies", async () => {
  const opened: unknown[] = [];
  class FakeRazorpay {
    constructor(private opts: { handler: (r: unknown) => void; order_id: string }) { opened.push(opts); }
    on() {}
    open() { this.opts.handler({ razorpay_order_id: this.opts.order_id, razorpay_payment_id: "pay_1", razorpay_signature: "sig" }); }
  }
  vi.stubGlobal("Razorpay", FakeRazorpay);
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/billing/orders")) return jsonResponse({ order_id: "order_ABC", key_id: "rzp_test_x", amount_paise: 4900,
      currency: "INR", credits: 500, name: "HootPR", description: "500 review credits — TEST MODE", prefill: { email: null, name: "A" } }, 201);
    if (url === "/api/billing/verify") return jsonResponse({ status: "paid", credits_added: "500.00", balance: "800.00" });
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<BuyCredits slug="acme" billing={billing} canBuy />);
  await userEvent.click(screen.getByRole("button", { name: /buy 500 credits for ₹49/i }));
  // Test-mode notice appears only at the moment of buying.
  expect(await screen.findByText(/no real money is charged or accepted/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /continue to checkout/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/billing/verify", expect.objectContaining({
    body: JSON.stringify({ razorpay_order_id: "order_ABC", razorpay_payment_id: "pay_1", razorpay_signature: "sig" }) })));
  expect((opened[0] as { key: string }).key).toBe("rzp_test_x");
});

test("blocked purchase shows the reason", () => {
  renderWithQuery(<BuyCredits slug="acme" canBuy
    billing={{ ...billing, can_purchase: false, purchase_blocked_reason: "Maximum of 2 packs reached." }} />);
  expect(screen.getByRole("button", { name: /buy 500 credits/i })).toBeDisabled();
  expect(screen.getByText("Maximum of 2 packs reached.")).toBeInTheDocument();
});
