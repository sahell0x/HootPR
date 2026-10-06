/**
 * Runtime configuration. The dashboard and the API are separate origins: the browser calls the API
 * directly at API_PUBLIC_URL, read from the web container's environment at REQUEST time (the root
 * layout renders it into `window.__HOOTPR__`), so a new API URL never needs an image rebuild.
 */
export interface RuntimeConfig {
  apiUrl: string;
}

declare global {
  interface Window {
    __HOOTPR__?: RuntimeConfig;
  }
}

const trim = (u: string) => u.replace(/\/+$/, "");

/** Server side: the public API URL from the environment (default: the local compose port). */
export function serverRuntimeConfig(): RuntimeConfig {
  return { apiUrl: trim(process.env.API_PUBLIC_URL || "http://localhost:8000") };
}

/** Base URL for API requests and links (no trailing slash). Empty = same origin (tests). */
export function apiBase(): string {
  if (typeof window === "undefined") return serverRuntimeConfig().apiUrl;
  return trim(window.__HOOTPR__?.apiUrl ?? "");
}

/** Absolute URL of an API path such as `/api/me`. */
export const apiUrl = (path: string) => `${apiBase()}${path}`;

/** The inline script the root layout renders (JSON-escaped for a <script> context). */
export function runtimeConfigScript(cfg: RuntimeConfig): string {
  return `window.__HOOTPR__=${JSON.stringify(cfg).replace(/</g, "\\u003c")};`;
}
