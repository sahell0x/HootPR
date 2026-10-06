import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import RepoSettingsPage from "@/app/o/[org]/repos/[repo]/settings/page";
import { configSchema } from "../fixtures/config-schema";
import { jsonResponse, renderWithQuery } from "../utils";

const orgBody = (role: string) => ({ id: "o1", slug: "acme", provider: "github", kind: "org", name: "acme",
  avatar_url: null, role, credits_balance: "300.00", installed: true, knowledge_base_opt_out: false });
const effective = { config: {}, provenance: {}, yaml: "# Effective HootPR configuration (source: defaults)\nlanguage: en-US\n",
  sources: ["default"], yaml_file_note: "A .hootpr.yaml on the default branch overrides these settings." };
const repo = { id: "r1", provider: "github", full_name: "acme/web", private: true, enabled: true,
  default_branch: "main", last_review_at: null };

test("422 invalid_settings shows errors next to fields", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/orgs/acme") return jsonResponse(orgBody("admin"));
    if (url === "/api/schema/hootpr.v1.json") return jsonResponse(configSchema);
    if (url === "/api/orgs/acme/repos/r1/effective-config") return jsonResponse(effective);
    if (init?.method === "PUT")
      return jsonResponse({ detail: { code: "invalid_settings", message: "Settings are invalid",
        errors: [{ line: null, path: "language", message: "Unknown language code" }] } }, 422);
    return jsonResponse({ repo, settings: { tools: { ruff: { enabled: false } } } });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<RepoSettingsPage />);
  expect(await screen.findByRole("heading", { name: "acme/web" })).toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: /^save$/i }));
  expect(await screen.findByText("Unknown language code")).toBeInTheDocument();
  // keys the form does not render survive a save
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/orgs/acme/repos/r1/settings",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({ settings: { tools: { ruff: { enabled: false } } } }) })));
});

test("non-admins get a read-only form", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme" ? jsonResponse(orgBody("member"))
      : url === "/api/schema/hootpr.v1.json" ? jsonResponse(configSchema)
      : url === "/api/orgs/acme/repos/r1/effective-config" ? jsonResponse(effective)
      : jsonResponse({ repo, settings: {} })));
  renderWithQuery(<RepoSettingsPage />);
  expect(await screen.findByRole("heading", { name: "acme/web" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("switch", { name: /poem/i })).toBeDisabled());
  expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
});

test("an unknown repository shows a not-found state", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme"
      ? jsonResponse({ id: "o1", slug: "acme", provider: "github", kind: "org", name: "acme", avatar_url: null,
          role: "admin", credits_balance: "200.00", installed: true, knowledge_base_opt_out: false })
      : jsonResponse({ detail: { code: "not_found", message: "Repository not found" } }, 404)));
  renderWithQuery(<RepoSettingsPage />);
  expect(await screen.findByRole("heading", { name: /this repository was not found/i })).toBeInTheDocument();
});

test("a successful save refreshes the effective configuration", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/orgs/acme") return jsonResponse(orgBody("admin"));
    if (url === "/api/schema/hootpr.v1.json") return jsonResponse(configSchema);
    if (url === "/api/orgs/acme/repos/r1/effective-config") return jsonResponse(effective);
    if (init?.method === "PUT") return jsonResponse({ repo, settings: { reviews: { poem: true } } });
    return jsonResponse({ repo, settings: {} });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<RepoSettingsPage />);
  expect(await screen.findByLabelText("Effective configuration YAML")).toHaveTextContent("language: en-US");
  const effectiveCalls = () => fetchMock.mock.calls.filter(([u]) => u === "/api/orgs/acme/repos/r1/effective-config").length;
  expect(effectiveCalls()).toBe(1);
  await userEvent.click(screen.getByRole("switch", { name: /poem/i }));
  await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(effectiveCalls()).toBe(2));
});

test("a failed schema request shows the error instead of the form", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/orgs/acme" ? jsonResponse(orgBody("admin"))
      : url === "/api/schema/hootpr.v1.json" ? jsonResponse({ detail: { code: "internal", message: "Schema unavailable" } }, 503)
      : url === "/api/orgs/acme/repos/r1/effective-config" ? jsonResponse(effective)
      : jsonResponse({ repo, settings: {} })));
  renderWithQuery(<RepoSettingsPage />);
  expect(await screen.findByText("Schema unavailable")).toBeInTheDocument();
});
