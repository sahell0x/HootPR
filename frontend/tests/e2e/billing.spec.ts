import { expect, test } from "@playwright/test";
import { billing, mockApi } from "./fixtures";

test("buy a credit pack in Razorpay test mode", async ({ page }) => {
  let verified: unknown = null;
  let paid = false;
  await page.route("https://checkout.razorpay.com/**", (route) => route.fulfill({ contentType: "application/javascript", body: "" }));
  await page.addInitScript(() => {
    (window as unknown as { Razorpay: unknown }).Razorpay = class {
      constructor(private o: { order_id: string; handler: (r: unknown) => void; key: string }) {}
      on() {}
      open() { this.o.handler({ razorpay_order_id: this.o.order_id, razorpay_payment_id: "pay_e2e", razorpay_signature: "sig" }); }
    };
  });
  await mockApi(page, {
    "GET /api/orgs/acme/billing": (route) => route.fulfill({ json: paid ? { ...billing, balance: "800.00", purchases_count: 1 } : billing }),
    "POST /api/orgs/acme/billing/orders": (route) => route.fulfill({ status: 201, json: { order_id: "order_E2E",
      key_id: "rzp_test_e2e", amount_paise: 4900, currency: "INR", credits: 500, name: "HootPR",
      description: "500 review credits — TEST MODE", prefill: { email: null, name: "Alice" } } }),
    "POST /api/billing/verify": async (route) => {
      verified = route.request().postDataJSON();
      paid = true;
      await route.fulfill({ json: { status: "paid", credits_added: "500.00", balance: "800.00" } });
    },
  });
  await page.goto("/o/acme/billing");
  await expect(page.getByText(/no real money/i)).toBeHidden();
  await page.getByRole("button", { name: /buy 500 credits for ₹49/i }).click();
  await expect(page.getByRole("dialog")).toContainText("no real money is charged or accepted");
  await page.getByRole("button", { name: /continue to checkout/i }).click();
  await expect(page.getByText(/added 500 credits/i)).toBeVisible();
  expect(verified).toEqual({ razorpay_order_id: "order_E2E", razorpay_payment_id: "pay_e2e", razorpay_signature: "sig" });
  await expect(page.getByText("1 / 2 packs bought")).toBeVisible();
});
