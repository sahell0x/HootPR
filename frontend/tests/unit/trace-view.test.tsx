import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { TraceView } from "@/components/trace-view";
import { reviewDetail } from "../fixtures/review";
import { jsonResponse, renderWithQuery } from "../utils";

test("timeline, degraded notice, tasks with steps, tools, judge", () => {
  renderWithQuery(<TraceView review={reviewDetail} slug="acme" />);
  const timeline = screen.getByRole("list", { name: /pipeline stages/i });
  expect(within(timeline).getAllByRole("listitem")).toHaveLength(6);
  expect(within(timeline).getByText("sandbox")).toBeInTheDocument();
  expect(within(timeline).getByText("5.2 s")).toBeInTheDocument();
  expect(within(timeline).getByText(/12 MB checkout, network sealed/)).toBeInTheDocument();
  expect(screen.getByText(/tools: failed or timed out: semgrep/i)).toBeInTheDocument();  // degraded alert
  const task = screen.getByRole("region", { name: /task 1: auth changes/i });
  expect(within(task).getByText("rg get_user", { exact: false })).toBeInTheDocument();
  expect(within(task).getByText(/stop reason: done/i)).toBeInTheDocument();
  const tools = screen.getByRole("table", { name: /tool runs/i });
  expect(within(tools).getByText("timeout")).toBeInTheDocument();
  const judge = screen.getByRole("table", { name: /judge verdicts/i });
  expect(within(judge).getAllByRole("row")).toHaveLength(4);  // header + 3 findings
  expect(within(judge).getByText("outside_changed_hunk")).toBeInTheDocument();
});

test("LLM calls show totals, errors and lazily load excerpts", async () => {
  const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({ ...reviewDetail.trace.llm_calls[1], request_excerpt: '{"messages":[]}',
                                                     response_excerpt: '{"choices":[]}' }));
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<TraceView review={reviewDetail} slug="acme" />);
  const table = screen.getByRole("table", { name: /llm calls/i });
  expect(within(table).getByText("gpt-6-luna")).toBeInTheDocument();
  expect(within(table).getByText("rate limited")).toBeInTheDocument();
  expect(within(table).getByText("Auth changes")).toBeInTheDocument();  // task column
  expect(within(table).getByText(/5400 \/ 2000 \/ 800/)).toBeInTheDocument();  // totals row
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(within(table).getAllByRole("button", { name: /show request/i })[1]!);
  expect(await screen.findByText('{"messages":[]}')).toBeInTheDocument();
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/orgs/acme/reviews/rev1/llm-calls/c2");
});

test("empty trace", () => {
  const empty = { ...reviewDetail, degraded: {}, findings: [],
                  trace: { stages: [], tasks: [], llm_calls: [], agent_steps: [], tool_runs: [] } };
  renderWithQuery(<TraceView review={empty} slug="acme" />);
  expect(screen.getByText(/no stages recorded/i)).toBeInTheDocument();
  // LLM calls are internal (only platform owners get them): no section when the API omits them.
  expect(screen.queryByText(/llm calls/i)).not.toBeInTheDocument();
});
