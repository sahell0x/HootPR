import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import OrgSettingsPage from "@/app/o/[org]/settings/page";
import { configSchema } from "../fixtures/config-schema";
import { jsonResponse, renderWithQuery } from "../utils";

const orgBody = (provider: string) => ({ id: "o1", slug: "acme", provider, kind: "group", name: "acme",
  avatar_url: null, role: "admin", credits_balance: "300.00", installed: false, knowledge_base_opt_out: false });

function mock(provider: string) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/orgs/acme") return jsonResponse(orgBody(provider));
    if (url === "/api/schema/hootpr.v1.json") return jsonResponse(configSchema);
    if (url === "/api/orgs/acme/settings" && init?.method === "PUT")
      return jsonResponse({ settings: { reviews: { poem: true } }, knowledge_base_opt_out: true });
    if (url === "/api/orgs/acme/settings") return jsonResponse({ settings: { reviews: { poem: true } }, knowledge_base_opt_out: false });
    if (url === "/api/orgs/acme/members") return jsonResponse({ members: [] });
    if (url === "/api/orgs/acme/gitlab/bot") return jsonResponse({ connected: false, bot_username: null, bot_user_id: null });
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

test("knowledge base opt-out keeps existing settings", async () => {
  const fetchMock = mock("github");
  renderWithQuery(<OrgSettingsPage />);
  await userEvent.click(await screen.findByRole("switch", { name: /opt out of learnings/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/orgs/acme/settings", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ settings: { reviews: { poem: true } }, knowledge_base_opt_out: true }) })));
  expect(screen.queryByText(/gitlab bot/i)).not.toBeInTheDocument();
  expect(screen.getByText(/members & roles/i)).toBeInTheDocument();
});

test("gitlab orgs show the bot card", async () => {
  mock("gitlab");
  renderWithQuery(<OrgSettingsPage />);
  expect(await screen.findByLabelText(/bot personal access token/i)).toBeInTheDocument();
});

test("a failed settings request shows the error instead of an endless skeleton", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme"
      ? jsonResponse(orgBody("github"))
      : jsonResponse({ detail: { code: "internal", message: "Settings unavailable" } }, 503)));
  renderWithQuery(<OrgSettingsPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Settings unavailable");
});

test("the org form is rendered from the schema", async () => {
  mock("github");
  renderWithQuery(<OrgSettingsPage />);
  expect(await screen.findByRole("switch", { name: /^poem$/i })).toBeChecked();
  expect(screen.getByText("Knowledge base", { selector: "summary" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add path instruction" })).toBeInTheDocument();
});
