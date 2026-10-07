import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  document.cookie = "hootpr_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  sessionStorage.clear();
});

vi.mock("next/navigation", () => {
  const push = vi.fn();
  const replace = vi.fn();
  const refresh = vi.fn();
  const back = vi.fn();
  return {
    useRouter: () => ({ push, replace, refresh, back }),
    usePathname: () => "/o/acme/repos",
    useParams: () => ({ org: "acme", repo: "r1", id: "rev1" }),
    useSearchParams: () => new URLSearchParams(),
    redirect: vi.fn(),
  };
});

// jsdom lacks ResizeObserver (used by Radix Switch/Checkbox size tracking).
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (typeof globalThis.IntersectionObserver === "undefined") {
  globalThis.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
}

// jsdom lacks pointer capture and scrollIntoView, which Radix Select uses when opening its menu.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};

if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
