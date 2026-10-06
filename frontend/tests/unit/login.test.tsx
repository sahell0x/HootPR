import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { LoginView } from "@/components/login-view";
import { SignupBonusNote } from "@/components/signup-bonus-note";
import { jsonResponse, renderWithQuery } from "../utils";

const meta = (github: boolean, gitlab: boolean, bonus = "300", perReview = "100") => ({
  github_app_slug: "hootpr",
  github_install_url: "https://github.com/apps/hootpr/installations/new",
  gitlab_base_url: "https://gitlab.com",
  razorpay_key_id: "rzp_test_x",
  billing_test_mode: true,
  disclaimer: "d",
  credit_pack: { credits: 500, price_paise: 4900, currency: "INR" },
  credit_prices: { per_review: perReview, per_chat_reply: "50", signup_bonus: bonus },
  providers_enabled: { github, gitlab },
});

function stubMeta(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => (url === "/api/meta" ? jsonResponse(body) : jsonResponse({}, 404))));
}

test("login shows both providers and maps error codes", () => {
  stubMeta(meta(true, true));
  renderWithQuery(<LoginView error="identity_in_use" next="/o/acme/repos" />);
  expect(screen.getByRole("link", { name: /sign in with github/i })).toHaveAttribute(
    "href",
    "/api/auth/github/login?next=%2Fo%2Facme%2Frepos",
  );
  expect(screen.getByRole("link", { name: /sign in with gitlab/i })).toHaveAttribute(
    "href",
    "/api/auth/gitlab/login?next=%2Fo%2Facme%2Frepos",
  );
  expect(screen.getByRole("alert")).toHaveTextContent("already linked to another HootPR user");
});

test("login without error shows no alert and ignores unsafe next", () => {
  stubMeta(meta(true, true));
  renderWithQuery(<LoginView next="https://evil.example/x" />);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /sign in with github/i })).toHaveAttribute(
    "href",
    "/api/auth/github/login",
  );
});

test("unknown error codes get a generic message", () => {
  stubMeta(meta(true, true));
  renderWithQuery(<LoginView error="weird" />);
  expect(screen.getByRole("alert")).toHaveTextContent(/sign-in failed/i);
});

test("a provider without OAuth keys is disabled and labelled", async () => {
  stubMeta(meta(true, false));
  renderWithQuery(<LoginView error="provider_not_configured" />);
  expect(await screen.findByText("Not configured on this server")).toBeInTheDocument();
  const gitlab = screen.getByRole("link", { name: /sign in with gitlab/i });
  expect(gitlab).toHaveAttribute("aria-disabled", "true");
  expect(gitlab).not.toHaveAttribute("href");
  expect(screen.getByRole("link", { name: /sign in with github/i })).toHaveAttribute("href", "/api/auth/github/login");
  expect(screen.getByRole("alert")).toHaveTextContent(/not configured on this server/i);
});

test("landing bonus note follows the configured credits, counted as typical metered reviews", async () => {
  stubMeta(meta(true, true, "400", "200"));
  renderWithQuery(<SignupBonusNote />);
  await waitFor(() => expect(screen.getByText(/start with free credits — about 4 typical reviews/i)).toBeInTheDocument());
});
