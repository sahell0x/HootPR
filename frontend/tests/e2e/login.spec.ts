import { expect, test } from "@playwright/test";
import { mockApi, org } from "./fixtures";

test("sign in, pick an org, land on repositories", async ({ page }) => {
  await mockApi(page, {
    "GET /api/auth/github/login": (route) => route.fulfill({ status: 302, headers: { location: "/orgs" } }),
    "GET /api/orgs/candidates": (route) => route.fulfill({ json: { orgs: [{ provider: "github", provider_org_id: "9001",
      kind: "org", name: "acme", avatar_url: null, slug: null, joined: false, installed: true, role: null, install_url: null }] } }),
    "POST /api/orgs/select": (route) => route.fulfill({ json: org }),
  });
  await page.goto("/");
  await expect(page.getByText(/no real money/i)).toHaveCount(0);
  await page.getByRole("link", { name: /sign in with github/i }).first().click();
  await expect(page).toHaveURL(/\/orgs$/);
  await page.getByRole("button", { name: "Select" }).click();
  // First navigation to /o/[org]/repos compiles the route in `next dev`; allow for it under parallel load.
  await expect(page).toHaveURL(/\/o\/acme\/repos$/, { timeout: 30_000 });
  await expect(page.getByText("acme/web")).toBeVisible();
});
