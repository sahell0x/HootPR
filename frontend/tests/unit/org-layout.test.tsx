import { screen, waitFor } from "@testing-library/react";
import { useRouter } from "next/navigation";
import { expect, test, vi } from "vitest";
import OrgLayout from "@/app/o/[org]/layout";
import { jsonResponse, renderWithQuery } from "../utils";

const me = { id: "u1", email: null, display_name: "Alice", avatar_url: null, csrf_token: "t", identities: [] };
const orgBody = { id: "o1", slug: "acme", provider: "github", kind: "org", name: "Acme Inc", avatar_url: null,
  role: "admin", credits_balance: "1250.00", installed: true, knowledge_base_opt_out: false };

test("signed-out users are redirected to login with next", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({ detail: { code: "unauthenticated", message: "no" } }, 401)),
  );
  renderWithQuery(<OrgLayout><p>child</p></OrgLayout>);
  await waitFor(() =>
    expect(useRouter().replace).toHaveBeenCalledWith("/login?next=%2Fo%2Facme%2Frepos"),
  );
  expect(screen.queryByText("child")).not.toBeInTheDocument();
});

test("unknown org shows not-found message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url === "/api/me" ? jsonResponse(me) : jsonResponse({ detail: { code: "not_found", message: "x" } }, 404),
    ),
  );
  renderWithQuery(<OrgLayout><p>child</p></OrgLayout>);
  expect(await screen.findByText(/organization not found or you are not a member/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /choose an organization/i })).toHaveAttribute("href", "/orgs");
});

test("renders the shell with credits pill and nav", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/me") return jsonResponse(me);
      if (url === "/api/orgs/acme") return jsonResponse(orgBody);
      if (url === "/api/orgs") return jsonResponse({ orgs: [orgBody] });
      return jsonResponse({}, 404);
    }),
  );
  renderWithQuery(<OrgLayout><p>child</p></OrgLayout>);
  expect(await screen.findByText("child")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /1,250 credits/i })).toHaveAttribute("href", "/o/acme/billing");
  expect(screen.getByRole("link", { name: /repositories/i })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: /reviews/i })).toHaveAttribute("href", "/o/acme/reviews");
});

test("nav links to the learnings page", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/me") return jsonResponse(me);
      if (url === "/api/orgs/acme") return jsonResponse(orgBody);
      if (url === "/api/orgs") return jsonResponse({ orgs: [orgBody] });
      return jsonResponse({}, 404);
    }),
  );
  renderWithQuery(<OrgLayout><p>child</p></OrgLayout>);
  expect(await screen.findByRole("link", { name: /learnings/i })).toHaveAttribute("href", "/o/acme/learnings");
});
