import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import ReviewDetailPage from "@/app/o/[org]/reviews/[id]/page";
import { reviewDetail } from "../fixtures/review";
import { jsonResponse, renderWithQuery } from "../utils";

test("shows findings grouped by judge outcome and the trace", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(reviewDetail)));
  renderWithQuery(<ReviewDetailPage />);
  expect(await screen.findByText("SQL injection via f-string")).toBeInTheDocument();
  expect(screen.getByText("2222222")).toBeInTheDocument();
  expect(screen.getByText(/2 of 3 files reviewed/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: /trace/i }));
  expect(await screen.findByText("gpt-5-nano")).toBeInTheDocument();
});

test("an invalid review id shows a not-found state instead of an endless skeleton", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    jsonResponse({ detail: [{ loc: ["path", "review_id"], msg: "Input should be a valid UUID", type: "uuid_parsing" }] }, 422)));
  renderWithQuery(<ReviewDetailPage />);
  expect(await screen.findByRole("heading", { name: /this review was not found/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /go back/i })).toHaveAttribute("href", "/o/acme/reviews");
});

const receipt = {
  reserved: "600.00", charged: "285.00", refunded: "315", minimum_applied: false, budget_reached: false,
  lines: [
    { stage: "learnings", label: "Learnings", credits: "5", input_tokens: null, cached_tokens: null, output_tokens: null, cost_usd: null },
    { stage: "agents", label: "Review agents", credits: "210.00", input_tokens: null, cached_tokens: null, output_tokens: null, cost_usd: null },
    { stage: "judge", label: "Verification", credits: "30", input_tokens: null, cached_tokens: null, output_tokens: null, cost_usd: null },
    { stage: "summarize", label: "Walkthrough", credits: "40", input_tokens: null, cached_tokens: null, output_tokens: null, cost_usd: null },
  ],
};

test("credit receipt itemises stages, the charge and what was returned — credits only for members", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...reviewDetail, receipt })));
  renderWithQuery(<ReviewDetailPage />);
  const card = await screen.findByTestId("credit-receipt");
  const c = within(card);
  expect(screen.getByRole("tab", { name: "Credits" })).toBeInTheDocument();
  expect(c.getByText("Review agents")).toBeInTheDocument();
  expect(c.getByText("210")).toBeInTheDocument();
  expect(c.getByTestId("receipt-charged")).toHaveTextContent("285");
  expect(c.getByText("Reserved 600 · Returned 315")).toBeInTheDocument();
  expect(c.getByRole("img", { name: "Credits by stage" })).toBeInTheDocument();
  expect(c.queryByText("Owner only")).not.toBeInTheDocument();
  expect(c.queryByRole("columnheader", { name: "Cost" })).not.toBeInTheDocument();
  expect(card).not.toHaveTextContent("$");
  expect(c.queryByText(/minimum charge/i)).not.toBeInTheDocument();
});

test("receipt notes the minimum charge and a trimmed review", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    jsonResponse({ ...reviewDetail, receipt: { ...receipt, minimum_applied: true, budget_reached: true } })));
  renderWithQuery(<ReviewDetailPage />);
  expect(await screen.findByText("Minimum charge applied")).toBeInTheDocument();
  expect(screen.getByText("Review trimmed to fit the reserved credits")).toBeInTheDocument();
});

test("a legacy (pre-metering) receipt shows one flat-rate line and a muted note", async () => {
  const legacy = { reserved: "100", charged: "100", refunded: "0", minimum_applied: false, budget_reached: false, legacy: true,
    lines: [{ stage: "flat", label: "Flat-rate review (before usage metering)", credits: "100",
      input_tokens: null, cached_tokens: null, output_tokens: null, cost_usd: null }] };
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...reviewDetail, receipt: legacy })));
  renderWithQuery(<ReviewDetailPage />);
  const c = within(await screen.findByTestId("credit-receipt"));
  expect(c.getByText("Flat-rate review (before usage metering)")).toBeInTheDocument();
  expect(c.getByTestId("receipt-legacy")).toHaveTextContent("This review was billed at the flat rate used before usage metering.");
  expect(c.queryByText("Other")).not.toBeInTheDocument();
});

test("no receipt, no Credits card", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...reviewDetail, receipt: null })));
  renderWithQuery(<ReviewDetailPage />);
  expect(await screen.findByText("SQL injection via f-string")).toBeInTheDocument();
  expect(screen.queryByTestId("credit-receipt")).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Credits" })).not.toBeInTheDocument();
});

test("platform owners also see tokens, $ cost and the margin, labelled owner only", async () => {
  const owner = { ...receipt, lines: [
    { stage: "agents", label: "Review agents", credits: "210", input_tokens: 12000, cached_tokens: 3000, output_tokens: 5000, cost_usd: "0.0100" },
    { stage: "summarize", label: "Walkthrough", credits: "75", input_tokens: 4000, cached_tokens: 0, output_tokens: 1000, cost_usd: "0.0020" },
  ] };
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...reviewDetail, receipt: owner })));
  renderWithQuery(<ReviewDetailPage />);
  const card = await screen.findByTestId("credit-receipt");
  const c = within(card);
  expect(c.getByRole("columnheader", { name: "Cost" })).toBeInTheDocument();
  expect(c.getByText("12,000")).toBeInTheDocument();
  expect(c.getByText("$0.0100")).toBeInTheDocument();
  expect(c.getByText("Owner only")).toBeInTheDocument();
  expect(c.getByTestId("receipt-margin")).toHaveTextContent("285 credits charged vs $0.0120 provider cost · $0.0042 per 100 credits");
});
