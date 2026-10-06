import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { expect, test, vi } from "vitest";
import OrgsPage from "@/app/orgs/page";
import { jsonResponse, renderWithQuery } from "../utils";

const me = {
  id: "u1",
  email: null,
  display_name: "Alice",
  avatar_url: null,
  csrf_token: "t",
  identities: [{ provider: "github", provider_user_id: "501", username: "alice" }],
};
const candidates = {
  orgs: [
    { provider: "github", provider_org_id: "501", kind: "personal", name: "alice", avatar_url: null, slug: "alice",
      joined: true, installed: true, role: "admin", install_url: null },
    { provider: "github", provider_org_id: "9001", kind: "org", name: "acme", avatar_url: null, slug: null,
      joined: false, installed: false, role: null,
      install_url: "https://github.com/apps/hootpr/installations/new/permissions?target_id=9001" },
  ],
};

test("lists candidates, installs and selects", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return jsonResponse(me);
    if (url === "/api/orgs/candidates") return jsonResponse(candidates);
    if (url === "/api/orgs/select" && init?.method === "POST")
      return jsonResponse({ id: "o2", slug: "acme", provider: "github", kind: "org", name: "acme", avatar_url: null,
        role: "admin", credits_balance: "300.00", installed: false, knowledge_base_opt_out: false });
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithQuery(<OrgsPage />);
  expect(await screen.findByText("acme")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /open/i })).toHaveAttribute("href", "/o/alice/repos");
  expect(screen.getByRole("link", { name: /install on github/i })).toHaveAttribute(
    "href",
    candidates.orgs[1]!.install_url,
  );
  expect(screen.getByRole("link", { name: /connect gitlab/i })).toHaveAttribute(
    "href",
    "/api/auth/gitlab/login?next=%2Forgs",
  );
  expect(screen.queryByRole("link", { name: /connect github/i })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /select/i }));
  await waitFor(() => expect(useRouter().push).toHaveBeenCalledWith("/o/acme/repos"));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/select",
    expect.objectContaining({ body: JSON.stringify({ provider: "github", provider_org_id: "9001" }) }),
  );
});

test("reauth_required sends the user to sign in", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url === "/api/me"
        ? jsonResponse(me)
        : jsonResponse({ detail: { code: "reauth_required", message: "expired" } }, 401),
    ),
  );
  renderWithQuery(<OrgsPage />);
  await waitFor(() => expect(useRouter().replace).toHaveBeenCalledWith("/login?error=oauth_failed"));
});

test("signed-out users are sent to login", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({ detail: { code: "unauthenticated", message: "no" } }, 401)),
  );
  renderWithQuery(<OrgsPage />);
  await waitFor(() => expect(useRouter().replace).toHaveBeenCalledWith("/login?next=%2Forgs"));
});

test.each([
  ["github_identity_required", /connect your github account first/i],
  ["not_a_member", /not a member of that github organization/i],
  ["installation_not_found", /try installing again/i],
  ["provider_error", /please try again/i],
])("install redirect error %s is explained", async (code, text) => {
  const { OrgsErrorAlert } = await import("@/components/orgs-error-alert");
  const { render } = await import("@testing-library/react");
  render(<OrgsErrorAlert code={code} />);
  expect(screen.getByRole("alert")).toHaveTextContent(text);
  const connect = screen.queryByRole("link", { name: /connect github/i });
  if (code === "github_identity_required") {
    expect(connect).toHaveAttribute("href", "/api/auth/github/login?next=%2Forgs");
  } else {
    expect(connect).not.toBeInTheDocument();
  }
});

test("the orgs page renders the ?error= alert", async () => {
  const nav = await import("next/navigation");
  const spy = vi.spyOn(nav, "useSearchParams").mockReturnValue(
    new URLSearchParams("error=not_a_member") as unknown as ReturnType<typeof nav.useSearchParams>,
  );
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/me" ? jsonResponse(me) : url === "/api/orgs/candidates" ? jsonResponse(candidates) : jsonResponse({}, 404)));
  renderWithQuery(<OrgsPage />);
  expect(await screen.findByText(/not a member of that github organization/i)).toBeInTheDocument();
  spy.mockRestore();
});
