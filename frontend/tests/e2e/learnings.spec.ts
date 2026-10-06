import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

const saved = { id: "l2", text: "Use logging.", scope: "org", repo_id: null, repo_full_name: null, path_glob: null,
  source_url: null, pr_number: null, created_by_username: "alice", embedded: false,
  created_at: "2026-09-29T09:00:00Z", updated_at: "2026-09-29T09:00:00Z" };

test("add a learning from the dashboard", async ({ page }) => {
  let posted: unknown = null;
  let csrf: string | null = null;
  await mockApi(page, {
    "POST /api/orgs/acme/learnings": async (route) => {
      posted = route.request().postDataJSON();
      csrf = await route.request().headerValue("x-csrf-token");
      await route.fulfill({ status: 201, json: saved });
    },
  });
  await page.goto("/o/acme/learnings");
  await expect(page.getByText(/No learnings yet/)).toBeVisible();
  await page.getByRole("button", { name: "Add learning" }).click();
  await page.getByRole("textbox", { name: "Learning" }).fill("Use logging.");
  await page.getByRole("combobox", { name: "Scope" }).click();
  await page.getByRole("option", { name: "Whole organization" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Learning saved")).toBeVisible();
  expect(posted).toEqual({ text: "Use logging.", scope: "org", repo_id: null, path_glob: null });
  expect(csrf).toBe("t");
});

test("filter by repository and delete a learning", async ({ page }) => {
  const listed: string[] = [];
  let deleted = false;
  await mockApi(page, {
    "GET /api/orgs/acme/learnings": async (route) => {
      listed.push(new URL(route.request().url()).search);
      await route.fulfill({ json: { learnings: deleted ? [] : [{ ...saved, scope: "repo", repo_id: "r1",
        repo_full_name: "acme/web", source_url: "https://github.com/acme/web/pull/7", pr_number: 7,
        embedded: true }], next_before: null } });
    },
    "DELETE /api/orgs/acme/learnings/l2": async (route) => {
      deleted = true;
      await route.fulfill({ status: 204 });
    },
  });
  await page.goto("/o/acme/learnings");
  const row = page.getByRole("row", { name: /Use logging\./ });
  await expect(row.getByRole("link", { name: "PR #7" })).toBeVisible();
  await page.getByRole("combobox", { name: "Repository" }).click();
  await page.getByRole("option", { name: "acme/web" }).click();
  await expect.poll(() => listed).toContain("?limit=50&repo_id=r1");
  await row.getByRole("button", { name: "Delete learning" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Learning deleted")).toBeVisible();
  await expect(page.getByText("No learnings match these filters.")).toBeVisible();
});
