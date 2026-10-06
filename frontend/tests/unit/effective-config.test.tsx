import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { EffectiveConfigPanel } from "@/components/effective-config";
import { jsonResponse, renderWithQuery } from "../utils";

test("shows provenance YAML and copies it with the schema header", async () => {
  const fetchMock = vi.fn(async () => jsonResponse({ config: {}, provenance: { "reviews.poem": "repo" },
    yaml: "# Effective HootPR configuration (source: repository settings)\nreviews:\n  poem: true  # from repository settings\n",
    sources: ["repo", "default"], yaml_file_note: "A .hootpr.yaml on the default branch overrides these settings." }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  renderWithQuery(<EffectiveConfigPanel slug="acme" repoId="r1" />);
  expect(await screen.findByLabelText("Effective configuration YAML")).toHaveTextContent("poem: true # from repository settings");
  expect(fetchMock).toHaveBeenCalledWith("/api/orgs/acme/repos/r1/effective-config", expect.anything());
  expect(screen.getByText(/overrides these settings/)).toBeInTheDocument();
  expect(screen.getByText(/from organization settings/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Copy as .hootpr.yaml" }));
  expect(writeText.mock.calls[0]?.[0]).toMatch(/^# yaml-language-server: \$schema=.*\/schema\/hootpr\.v1\.json\n# Effective/);
});

test("a failed request shows the error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: { code: "internal", message: "Config unavailable" } }, 503)));
  renderWithQuery(<EffectiveConfigPanel slug="acme" repoId="r1" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Config unavailable");
});
