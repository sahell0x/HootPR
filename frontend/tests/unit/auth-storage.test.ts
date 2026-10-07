import { beforeEach, describe, expect, test } from "vitest";
import type { Org } from "@/lib/api-types";
import {
  clearAuthStorage,
  getDashboardUrl,
  getLastOrg,
  hasAuthHint,
  setAuthHint,
  setLastOrg,
} from "@/lib/auth-storage";

const sampleOrg = (slug: string): Org => ({
  id: `id-${slug}`,
  slug,
  provider: "github",
  kind: "org",
  name: `Org ${slug}`,
  avatar_url: null,
  role: "admin",
  credits_balance: "100.00",
  installed: true,
  knowledge_base_opt_out: false,
});

describe("auth-storage", () => {
  beforeEach(() => {
    clearAuthStorage();
    localStorage.clear();
  });

  test("hasAuthHint reflects setAuthHint and clearAuthStorage", () => {
    expect(hasAuthHint()).toBe(false);

    setAuthHint(true);
    expect(hasAuthHint()).toBe(true);

    setAuthHint(false);
    expect(hasAuthHint()).toBe(false);

    setAuthHint(true);
    clearAuthStorage();
    expect(hasAuthHint()).toBe(false);
  });

  test("getLastOrg and setLastOrg persist and clear", () => {
    expect(getLastOrg()).toBeNull();

    setLastOrg("my-team");
    expect(getLastOrg()).toBe("my-team");

    clearAuthStorage();
    expect(getLastOrg()).toBeNull();
  });

  test("getDashboardUrl returns /orgs when no orgs exist", () => {
    expect(getDashboardUrl([])).toBe("/orgs");
    expect(getDashboardUrl(null)).toBe("/orgs");
    expect(getDashboardUrl(undefined)).toBe("/orgs");
  });

  test("getDashboardUrl returns lastOrg when present in user orgs", () => {
    setLastOrg("team-b");
    const orgs = [sampleOrg("team-a"), sampleOrg("team-b")];
    expect(getDashboardUrl(orgs)).toBe("/o/team-b/repos");
  });

  test("getDashboardUrl falls back to first org when lastOrg is not in user orgs", () => {
    setLastOrg("removed-team");
    const orgs = [sampleOrg("team-a"), sampleOrg("team-b")];
    expect(getDashboardUrl(orgs)).toBe("/o/team-a/repos");
  });
});
