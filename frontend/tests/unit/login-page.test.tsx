import { screen, waitFor } from "@testing-library/react";
import { useRouter } from "next/navigation";
import { beforeEach, expect, test, vi } from "vitest";
import LoginPage from "@/app/login/page";
import { clearAuthStorage, setAuthHint } from "@/lib/auth-storage";
import { jsonResponse, renderWithQuery } from "../utils";

const me = {
  id: "u1",
  email: "alice@example.com",
  display_name: "Alice",
  avatar_url: null,
  csrf_token: "csrf",
  identities: [{ provider: "github", provider_user_id: "1", username: "alice" }],
};

const org1 = {
  id: "o1",
  slug: "acme",
  provider: "github",
  kind: "org",
  name: "Acme",
  avatar_url: null,
  role: "admin",
  credits_balance: "500.00",
  installed: true,
  knowledge_base_opt_out: false,
};

const meta = {
  github_app_slug: "hootpr",
  github_install_url: "https://github.com/apps/hootpr/installations/new",
  gitlab_base_url: "https://gitlab.com",
  razorpay_key_id: "rzp_test_x",
  billing_test_mode: true,
  disclaimer: "d",
  credit_pack: { credits: 500, price_paise: 4900, currency: "INR" },
  credit_prices: { per_review: "100", per_chat_reply: "50", signup_bonus: "300" },
  providers_enabled: { github: true, gitlab: true },
};

beforeEach(() => {
  clearAuthStorage();
  localStorage.clear();
  vi.clearAllMocks();
});

test("logged-out user sees the login view", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/meta") return jsonResponse(meta);
      if (url === "/api/me") return jsonResponse({ detail: { code: "unauthenticated", message: "no" } }, 401);
      return jsonResponse({}, 404);
    }),
  );

  renderWithQuery(<LoginPage />);

  expect(await screen.findByRole("heading", { name: /sign in to hootpr/i })).toBeVisible();
  expect(useRouter().replace).not.toHaveBeenCalled();
});

test("logged-in user on /login redirects to dashboard directly", async () => {
  setAuthHint(true);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/meta") return jsonResponse(meta);
      if (url === "/api/me") return jsonResponse(me);
      if (url === "/api/orgs") return jsonResponse({ orgs: [org1] });
      return jsonResponse({}, 404);
    }),
  );

  renderWithQuery(<LoginPage />);

  await waitFor(() => {
    expect(useRouter().replace).toHaveBeenCalledWith("/o/acme/repos");
  });
  expect(screen.queryByRole("heading", { name: /sign in to hootpr/i })).not.toBeInTheDocument();
});
