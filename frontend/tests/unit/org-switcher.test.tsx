import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { expect, test, vi } from "vitest";
import { OrgSwitcher } from "@/components/org-switcher";
import { jsonResponse, renderWithQuery } from "../utils";

const org = (slug: string, name: string, provider = "github") => ({ id: slug, slug, provider, kind: "org", name,
  avatar_url: null, role: "admin", credits_balance: "300.00", installed: true, knowledge_base_opt_out: false });

test("switches organizations", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({ orgs: [org("acme", "Acme"), org("gl-beta", "Beta", "gitlab")] })),
  );
  renderWithQuery(<OrgSwitcher current="acme" />);
  await userEvent.click(await screen.findByRole("button", { name: /acme/i }));
  await userEvent.click(await screen.findByRole("menuitem", { name: /beta/i }));
  expect(useRouter().push).toHaveBeenCalledWith("/o/gl-beta/repos");
});

test("offers adding an organization", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ orgs: [org("acme", "Acme")] })));
  renderWithQuery(<OrgSwitcher current="acme" />);
  await userEvent.click(await screen.findByRole("button", { name: /acme/i }));
  await userEvent.click(await screen.findByRole("menuitem", { name: /add organization/i }));
  expect(useRouter().push).toHaveBeenCalledWith("/orgs");
});
