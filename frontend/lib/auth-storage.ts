import type { Org } from "./api-types";

const AUTHED_KEY = "hootpr_authed";
const LAST_ORG_KEY = "hootpr_last_org";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null;
}

function writeCookie(name: string, value: string, maxAgeDays = 14) {
  if (typeof document === "undefined") return;
  const maxAge = maxAgeDays * 24 * 60 * 60;
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; SameSite=Lax`;
}

function deleteCookie(name: string) {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax`;
}

export function hasAuthHint(): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (localStorage.getItem(AUTHED_KEY) === "1") return true;
  } catch {
    /* ignore storage access error */
  }
  return readCookie(AUTHED_KEY) === "1";
}

export function setAuthHint(authed: boolean) {
  if (typeof window === "undefined") return;
  try {
    if (authed) {
      localStorage.setItem(AUTHED_KEY, "1");
      writeCookie(AUTHED_KEY, "1");
    } else {
      localStorage.removeItem(AUTHED_KEY);
      deleteCookie(AUTHED_KEY);
    }
  } catch {
    /* ignore */
  }
}

export function getLastOrg(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const val = localStorage.getItem(LAST_ORG_KEY);
    if (val) return val;
  } catch {
    /* ignore */
  }
  return readCookie(LAST_ORG_KEY);
}

export function setLastOrg(slug: string) {
  if (typeof window === "undefined" || !slug) return;
  try {
    localStorage.setItem(LAST_ORG_KEY, slug);
    writeCookie(LAST_ORG_KEY, slug);
  } catch {
    /* ignore */
  }
}

export function clearAuthStorage() {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(AUTHED_KEY);
    localStorage.removeItem(LAST_ORG_KEY);
  } catch {
    /* ignore */
  }
  deleteCookie(AUTHED_KEY);
  deleteCookie(LAST_ORG_KEY);
}

/** Given organizations list, determine the best dashboard destination. */
export function getDashboardUrl(orgs?: Org[] | null): string {
  if (!orgs || orgs.length === 0) {
    return "/orgs";
  }
  const last = getLastOrg();
  if (last && orgs.some((o) => o.slug === last)) {
    return `/o/${encodeURIComponent(last)}/repos`;
  }
  const first = orgs[0];
  if (first) {
    return `/o/${encodeURIComponent(first.slug)}/repos`;
  }
  return "/orgs";
}
