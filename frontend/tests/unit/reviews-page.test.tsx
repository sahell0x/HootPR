import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import ReviewsPage from "@/app/o/[org]/reviews/page";
import { jsonResponse, renderWithQuery } from "../utils";

const row = (id: string, status: string) => ({ id, repo_full_name: "acme/web", pr_number: 7, pr_title: "Add rate limit",
  pr_url: "https://github.com/acme/web/pull/7", trigger: "auto", status, skip_reason: null, credits_charged: "100.00",
  findings_posted: 0, files_considered: 3, input_tokens: null, output_tokens: null, cost_usd: null,
  created_at: "2026-09-28T10:00:00Z", finished_at: null });

test("lists reviews and paginates", async () => {
  const fetchMock = vi.fn(async (url: string) =>
    url.includes("before=")
      ? jsonResponse({ reviews: [row("r3", "rate_limited")], next_before: null })
      : jsonResponse({ reviews: [row("r1", "completed"), row("r2", "no_credits")], next_before: "2026-09-27T00:00:00Z" }));
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<ReviewsPage />);
  expect(await screen.findByText("Completed")).toBeInTheDocument();
  expect(screen.getByText("Out of credits")).toBeInTheDocument();
  // tokens / LLM cost are internal: hidden when the API does not return them (non-owners)
  expect(screen.queryByRole("columnheader", { name: /tokens|cost/i })).not.toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Credits" })).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: /acme\/web#7/ })[0]).toHaveAttribute("href", "https://github.com/acme/web/pull/7");
  await userEvent.click(screen.getByRole("button", { name: /load more/i }));
  expect(await screen.findByText("Rate limited")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
});
