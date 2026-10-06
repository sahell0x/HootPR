import { expect, test } from "@playwright/test";

test("landing shows the pitch and sign-in links, with no test-mode or portfolio notice", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Code reviews that never sleep." })).toBeVisible();
  await expect(page.getByRole("link", { name: /sign in with github/i })).toHaveAttribute(
    "href",
    "/api/auth/github/login",
  );
  await expect(page.getByText(/no real money|portfolio/i)).toHaveCount(0);
});

test("login maps error codes", async ({ page }) => {
  await page.goto("/login?error=oauth_state_invalid&next=/o/acme/repos");
  await expect(page.getByRole("alert").filter({ hasText: "Your sign-in link expired" })).toBeVisible();
  await expect(page.getByRole("link", { name: /sign in with gitlab/i })).toHaveAttribute(
    "href",
    "/api/auth/gitlab/login?next=%2Fo%2Facme%2Frepos",
  );
});

test("org shell redirects signed-out users to login", async ({ page }) => {
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 401, json: { detail: { code: "unauthenticated", message: "Sign in" } } }),
  );
  await page.goto("/o/acme/repos");
  await expect(page).toHaveURL(/\/login\?next=%2Fo%2Facme%2Frepos$/);
});
