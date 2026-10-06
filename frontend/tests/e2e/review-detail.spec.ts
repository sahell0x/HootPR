import { expect, test } from "@playwright/test";
import { reviewDetail } from "../fixtures/review";
import { mockApi } from "./fixtures";

test("review detail: findings groups, judge filter, trace with lazy LLM excerpts", async ({ page }) => {
  let excerptCalls = 0;
  await mockApi(page, {
    "GET /api/orgs/acme/reviews/rev1": (route) => route.fulfill({ json: reviewDetail }),
    "GET /api/orgs/acme/reviews/rev1/llm-calls/c1": (route) => {
      excerptCalls += 1;
      return route.fulfill({ json: { ...reviewDetail.trace.llm_calls[0], request_excerpt: "REQUEST-BODY",
                                     response_excerpt: "RESPONSE-BODY" } });
    },
  });
  await page.goto("/o/acme/reviews/rev1");
  await expect(page.getByText("SQL injection via f-string")).toBeVisible();
  await expect(page.getByText("Far away")).toBeHidden();
  await page.getByRole("button", { name: /show 1 finding filtered out/i }).click();
  await expect(page.getByText("outside_changed_hunk").first()).toBeVisible();
  await page.getByRole("tab", { name: /trace/i }).click();
  await expect(page.getByRole("list", { name: /pipeline stages/i })).toBeVisible();
  expect(excerptCalls).toBe(0);
  await page.getByRole("button", { name: /show request and response of call c1/i }).click();
  await expect(page.getByText("REQUEST-BODY")).toBeVisible();
  expect(excerptCalls).toBe(1);
});
