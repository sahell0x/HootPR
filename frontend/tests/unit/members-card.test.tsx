import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MembersCard } from "@/components/members-card";
import { jsonResponse, renderWithQuery, pickOption } from "../utils";

test("admin changes a role", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") return jsonResponse({ user_id: "u2", display_name: "Bob", username: "bob", avatar_url: null, role: "billing_admin" });
    return jsonResponse({ members: [
      { user_id: "u1", display_name: "Alice", username: "alice", avatar_url: null, role: "admin" },
      { user_id: "u2", display_name: "Bob", username: "bob", avatar_url: null, role: "member" }] });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<MembersCard slug="acme" isAdmin />);
  await pickOption(await screen.findByLabelText("Role for Bob"), "billing_admin");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/orgs/acme/members/u2",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ role: "billing_admin" }) })));
});

test("members see roles read-only", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ members: [
    { user_id: "u1", display_name: "Alice", username: "alice", avatar_url: null, role: "admin" }] })));
  renderWithQuery(<MembersCard slug="acme" isAdmin={false} />);
  expect(await screen.findByText("admin")).toBeInTheDocument();
  expect(screen.queryByLabelText("Role for Alice")).not.toBeInTheDocument();
});
