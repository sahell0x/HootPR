import { expect, test } from "vitest";
import { getPath, setPath, splitList, unsetPath } from "@/lib/settings-paths";

test("path helpers are immutable and prune", () => {
  const a = { reviews: { poem: true } };
  const b = setPath(a, "reviews.auto_review.drafts", true);
  expect(a).toEqual({ reviews: { poem: true } });
  expect(getPath(b, "reviews.auto_review.drafts")).toBe(true);
  expect(unsetPath(unsetPath(b, "reviews.auto_review.drafts"), "reviews.poem")).toEqual({});
});

test("splitList splits lines and commas and drops blanks", () => {
  expect(splitList("a, b\n\n c ,")).toEqual(["a", "b", "c"]);
});
