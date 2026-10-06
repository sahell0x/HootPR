import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { GitlabBotCard } from "@/components/gitlab-bot-card";
import { jsonResponse, renderWithQuery } from "../utils";

test("connect shows invalid token error", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") return jsonResponse({ detail: { code: "invalid_token", message: "GitLab rejected this token" } }, 400);
    return jsonResponse({ connected: false, bot_username: null, bot_user_id: null });
  }));
  renderWithQuery(<GitlabBotCard slug="gl-acme" isAdmin />);
  await userEvent.type(await screen.findByLabelText(/bot personal access token/i), "glpat-bad");
  await userEvent.click(screen.getByRole("button", { name: /connect/i }));
  expect(await screen.findByText(/needs the api, read_api and read_user scopes/i)).toBeInTheDocument();
});

test("connected bot lists projects and saves selection", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/gitlab/bot")) return jsonResponse({ connected: true, bot_username: "hootpr-bot", bot_user_id: 5 });
    if (url.endsWith("/gitlab/projects") && init?.method === "PUT") return jsonResponse({ repos: [], can_install: true, install_url: null });
    return jsonResponse({ whole_group: false, projects: [
      { id: 2002, path_with_namespace: "acme-group/api", selected: false },
      { id: 2003, path_with_namespace: "acme-group/web", selected: true }] });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<GitlabBotCard slug="gl-acme" isAdmin />);
  expect(await screen.findByText(/connected as @hootpr-bot/i)).toBeInTheDocument();
  await userEvent.click(await screen.findByRole("checkbox", { name: "acme-group/api" }));
  await userEvent.click(screen.getByRole("button", { name: /save projects/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/orgs/gl-acme/gitlab/projects",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({ project_ids: [2003, 2002], whole_group: false }) })));
});
