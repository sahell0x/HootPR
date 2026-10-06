import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

test("save repository settings sends only overrides with csrf", async ({ page }) => {
  let body: unknown = null;
  let csrf: string | null = null;
  await mockApi(page, {
    "PUT /api/orgs/acme/repos/r1/settings": async (route) => {
      body = route.request().postDataJSON();
      csrf = await route.request().headerValue("x-csrf-token");
      await route.fulfill({ json: { repo: { id: "r1", provider: "github", full_name: "acme/web", private: true,
        enabled: true, default_branch: "main", last_review_at: null }, settings: (body as { settings: unknown }).settings } });
    },
  });
  await page.goto("/o/acme/repos/r1/settings");
  await page.getByRole("switch", { name: "Poem" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  expect(body).toEqual({ settings: { reviews: { poem: true } } });
  expect(csrf).toBe("t");
});

test("repository settings: add a path instruction and see the effective config", async ({ page }) => {
  let body: unknown = null;
  await mockApi(page, {
    "PUT /api/orgs/acme/repos/r1/settings": async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { repo: { id: "r1", provider: "github", full_name: "acme/web", private: true,
        enabled: true, default_branch: "main", last_review_at: null }, settings: (body as { settings: unknown }).settings } });
    },
  });
  await page.goto("/o/acme/repos/r1/settings");
  await page.getByText("Path filters & instructions").click();
  await page.getByRole("button", { name: "Add path instruction" }).click();
  await page.getByRole("textbox", { name: "Path instruction 1 path" }).fill("src/api/**");
  await page.getByRole("textbox", { name: "Path instruction 1 instructions" }).fill("Check auth.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  expect(body).toEqual({ settings: { reviews: { path_instructions: [{ path: "src/api/**", instructions: "Check auth." }] } } });
  await expect(page.getByLabel("Effective configuration YAML")).toBeVisible();
});

test("organization settings: an ast-grep rule with invalid YAML cannot be saved", async ({ page }) => {
  let body: unknown = null;
  await mockApi(page, {
    "GET /api/orgs/acme/settings": (route) => route.fulfill({ json: { settings: {}, knowledge_base_opt_out: false } }),
    "GET /api/orgs/acme/members": (route) => route.fulfill({ json: { members: [] } }),
    "PUT /api/orgs/acme/settings": async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { settings: (body as { settings: unknown }).settings, knowledge_base_opt_out: false } });
    },
  });
  await page.goto("/o/acme/settings");
  await page.locator("summary", { hasText: "AST-grep" }).click();
  await page.getByRole("button", { name: "Add ast-grep instruction" }).click();
  await page.getByRole("textbox", { name: "Ast-grep instruction 1 id" }).fill("no-print");
  await page.getByRole("textbox", { name: "Ast-grep instruction 1 language" }).fill("python");
  await page.getByRole("textbox", { name: "Ast-grep instruction 1 message" }).fill("Use logging.");
  const rule = page.getByRole("textbox", { name: "Ast-grep instruction 1 rule" });
  await rule.fill("pattern: [unclosed");
  await expect(page.getByText(/Invalid YAML/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  await rule.fill("pattern: print($$$A)");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  expect(body).toEqual({ settings: { reviews: { ast_grep_instructions: [
    { id: "no-print", language: "python", message: "Use logging.", rule: { pattern: "print($$$A)" } }] } } });
});
