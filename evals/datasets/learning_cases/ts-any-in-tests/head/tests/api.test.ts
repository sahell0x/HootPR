import { describe, expect, it, vi } from "vitest";

import { fetchUser } from "../src/api";

describe("fetchUser", () => {
  it("returns the parsed user", async () => {
    const fake = { ok: true, json: async () => ({ id: 1, name: "Ada" }) };
    vi.stubGlobal("fetch", vi.fn(async () => fake as any));
    const user = await fetchUser(1);
    expect((user as any).name).toBe("Ada");
  });
});
