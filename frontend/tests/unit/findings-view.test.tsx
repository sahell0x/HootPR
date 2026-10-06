import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { FindingsView } from "@/components/findings-view";
import { reviewDetail } from "../fixtures/review";

test("groups findings: posted, walkthrough, filtered (collapsed)", async () => {
  render(<FindingsView review={reviewDetail} />);
  const posted = screen.getByRole("region", { name: /posted as inline comments/i });
  expect(within(posted).getByText("SQL injection via f-string")).toBeInTheDocument();
  expect(within(posted).getByText("Critical")).toBeInTheDocument();
  expect(within(posted).getByText("src/login.py · L2–L3")).toBeInTheDocument();
  expect(within(posted).getByText('q = "select * from users where name=%s"', { exact: false })).toBeInTheDocument();
  expect(within(posted).getByText(/verified against the query builder/)).toBeInTheDocument();
  const walk = screen.getByRole("region", { name: /in the walkthrough/i });
  expect(within(walk).getByText("Rename q")).toBeInTheDocument();
  expect(screen.queryByText("Far away")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show 1 finding filtered out/i }));
  expect(screen.getByText("Far away")).toBeInTheDocument();
  expect(screen.getByText(/outside_changed_hunk/)).toBeInTheDocument();
});

test("severity filter", async () => {
  render(<FindingsView review={reviewDetail} />);
  await userEvent.click(screen.getByRole("button", { name: "Nitpick" }));
  expect(screen.queryByText("SQL injection via f-string")).not.toBeInTheDocument();
  expect(screen.getByText("Rename q")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "All" }));
  expect(screen.getByText("SQL injection via f-string")).toBeInTheDocument();
});

test("a severity with no matches says so instead of rendering nothing", async () => {
  render(<FindingsView review={reviewDetail} />);
  await userEvent.click(screen.getByRole("button", { name: "Major" }));
  expect(screen.getByText(/no major findings/i)).toBeInTheDocument();
});

test("empty states depend on the review status", () => {
  const { rerender } = render(<FindingsView review={{ ...reviewDetail, findings: [] }} />);
  expect(screen.getByText(/no issues found/i)).toBeInTheDocument();
  rerender(<FindingsView review={{ ...reviewDetail, status: "skipped", skip_reason: "no_reviewable_files", findings: [] }} />);
  expect(screen.getByText(/skipped: no_reviewable_files/i)).toBeInTheDocument();
  rerender(<FindingsView review={{ ...reviewDetail, status: "running", findings: [] }} />);
  expect(screen.getByText(/review is still running/i)).toBeInTheDocument();
});
