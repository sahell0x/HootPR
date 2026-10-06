import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import ReposPage from "@/app/o/[org]/repos/page";
import { jsonResponse, renderWithQuery } from "../utils";

const orgBody = { id: "o1", slug: "acme", provider: "github", kind: "org", name: "acme", avatar_url: null,
  role: "admin", credits_balance: "300.00", installed: true, knowledge_base_opt_out: false };
const repo = { id: "r1", provider: "github", full_name: "acme/web", private: true, enabled: true,
  default_branch: "main", last_review_at: null };
const installUrl = "https://github.com/apps/hootpr/installations/new/permissions?target_id=9001";

test("lists repos, toggles enabled and syncs", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/orgs/acme") return jsonResponse(orgBody);
    if (url === "/api/orgs/acme/repos")
      return jsonResponse({ repos: [repo], can_install: true, install_url: installUrl });
    if (url === "/api/orgs/acme/repos/r1" && init?.method === "PATCH") return jsonResponse({ ...repo, enabled: false });
    if (url === "/api/orgs/acme/repos/sync") return jsonResponse({ status: "queued" }, 202);
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<ReposPage />);
  expect(await screen.findByText("acme/web")).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /add repositories/i })).toHaveAttribute(
    "href",
    expect.stringContaining("target_id=9001"),
  );
  await userEvent.click(screen.getByRole("switch", { name: /enable acme\/web/i }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/orgs/acme/repos/r1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ enabled: false }) }),
    ),
  );
  await userEvent.click(screen.getByRole("button", { name: /sync/i }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith("/api/orgs/acme/repos/sync", expect.objectContaining({ method: "POST" })),
  );
  expect(screen.getByRole("link", { name: /settings/i })).toHaveAttribute("href", "/o/acme/repos/r1/settings");
});

test("members see disabled switches and no admin actions", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/orgs/acme") return jsonResponse({ ...orgBody, role: "member" });
      if (url === "/api/orgs/acme/repos")
        return jsonResponse({ repos: [repo], can_install: false, install_url: null });
      return jsonResponse({}, 404);
    }),
  );
  renderWithQuery(<ReposPage />);
  expect(await screen.findByText("acme/web")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("switch", { name: /enable acme\/web/i })).toBeDisabled());
  expect(screen.queryByRole("button", { name: /sync/i })).not.toBeInTheDocument();
});

test("empty GitLab org points admins at the bot setup", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/orgs/acme")
        return jsonResponse({ ...orgBody, provider: "gitlab", kind: "group", installed: false });
      if (url === "/api/orgs/acme/repos") return jsonResponse({ repos: [], can_install: false, install_url: null });
      return jsonResponse({}, 404);
    }),
  );
  renderWithQuery(<ReposPage />);
  expect(await screen.findByText(/no repositories yet/i)).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /connect gitlab bot/i })).toHaveAttribute(
    "href",
    "/o/acme/settings#gitlab",
  );
});
