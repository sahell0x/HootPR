import { expect, test } from "vitest";
import { formatMs, formatPct, lineSpan, severityRank } from "@/lib/format";
import {
  creditsLabel,
  formatCredits,
  formatInr,
  formatUsd,
  reviewsFor,
  shortSha,
  STATUS_LABEL,
  timeAgo,
} from "@/lib/format";

test("formatters", () => {
  expect(formatCredits("300.00")).toBe("300");
  expect(formatCredits("285")).toBe("285");
  expect(formatCredits(1250)).toBe("1,250");
  expect(formatCredits("-50.00")).toBe("-50");
  expect(formatCredits("0.00")).toBe("0");
  expect(formatUsd(null)).toBe("—");
  expect(formatUsd("0.000123")).toBe("$0.000123");
  expect(formatInr(4900)).toBe("₹49");
  expect(shortSha("abcdef1234")).toBe("abcdef1");
  expect(timeAgo("2026-09-28T10:00:00Z", new Date("2026-09-28T10:05:00Z"))).toBe("5m ago");
  expect(timeAgo("2026-09-26T10:00:00Z", new Date("2026-09-28T10:00:00Z"))).toBe("2d ago");
  expect(timeAgo("2026-09-28T10:00:00Z", new Date("2026-09-28T10:00:20Z"))).toBe("just now");
  expect(STATUS_LABEL.no_credits).toBe("Out of credits");
});

test("credit labels follow the configured prices", () => {
  expect(creditsLabel("1")).toBe("1 credit");
  expect(creditsLabel("10.00")).toBe("10 credits");
  expect(creditsLabel("1000")).toBe("1,000 credits");
  expect(reviewsFor("300", "100")).toBe(3);
  expect(reviewsFor("500", "200")).toBe(2);
  expect(reviewsFor("300", "0")).toBe(0);
});

test("formatMs", () => {
  expect(formatMs(null)).toBe("—");
  expect(formatMs(850)).toBe("850 ms");
  expect(formatMs(2300)).toBe("2.3 s");
  expect(formatMs(65_000)).toBe("1m 05s");
  expect(formatMs(119_600)).toBe("2m 00s");
});

test("formatPct, lineSpan, severityRank", () => {
  expect(formatPct(0.953)).toBe("95%");
  expect(formatPct(null)).toBe("—");
  expect(lineSpan(3, 7)).toBe("L3–L7");
  expect(lineSpan(null, 7)).toBe("L7");
  expect(lineSpan(7, 7)).toBe("L7");
  expect(["nitpick", "critical", "minor", "major"].sort((a, b) => severityRank(a) - severityRank(b)))
    .toEqual(["critical", "major", "minor", "nitpick"]);
  expect(severityRank("weird")).toBe(4);
});
