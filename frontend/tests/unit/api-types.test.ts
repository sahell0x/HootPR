// Guards spec §12: lib/openapi.d.ts must be what openapi-typescript generates from the backend's
// committed OpenAPI schema (which backend tests keep in sync with FastAPI). Fix: `make api-types`.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(import.meta.dirname, "../..");

describe("generated API types", () => {
  it("lib/openapi.d.ts matches backend/openapi.json", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "hootpr-openapi-"));
    try {
      const out = path.join(dir, "openapi.d.ts");
      execFileSync(
        path.join(root, "node_modules/.bin/openapi-typescript"),
        [path.join(root, "../backend/openapi.json"), "-o", out],
        { stdio: "pipe" },
      );
      const committed = readFileSync(path.join(root, "lib/openapi.d.ts"), "utf8");
      expect(readFileSync(out, "utf8")).toBe(committed);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }, 30_000);
});
