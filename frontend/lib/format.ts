import type { ReviewStatus, Severity } from "./api-types";

/** Credits are whole numbers: "285.00" → "285", 1250 → "1,250". */
export const formatCredits = (v: string | number) =>
  (Math.round(Number(v)) || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
/** "1 credit", "3 credits", "1,250 credits". */
export const creditsLabel = (v: string | number) =>
  `${formatCredits(v)} ${Math.round(Number(v)) === 1 ? "credit" : "credits"}`;
/** Reviews are billed by actual AI usage; the rate card is calibrated so a typical review is ≈ 100 credits. */
export const TYPICAL_REVIEW_CREDITS = 100;
/** Whole reviews a credit amount pays for (e.g. the signup bonus). */
export const reviewsFor = (credits: string | number, perReview: string | number) =>
  Number(perReview) > 0 ? Math.floor(Number(credits) / Number(perReview)) : 0;
export const formatUsd = (v: string | null | undefined) => (v == null ? "—" : `$${v}`);
export const formatInr = (paise: number) =>
  `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
export const shortSha = (sha: string) => sha.slice(0, 7);

export function timeAgo(iso: string, now: Date = new Date()): string {
  const s = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const STATUS_LABEL: Record<ReviewStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  skipped: "Skipped",
  rate_limited: "Rate limited",
  no_credits: "Out of credits",
};

/** Most to least severe; spec §7.6 severities. */
export const SEVERITY_ORDER: Severity[] = ["critical", "major", "minor", "nitpick"];
/** Sort key: critical=0 … nitpick=3, anything unknown last. */
export const severityRank = (s: string) => {
  const i = SEVERITY_ORDER.indexOf(s as Severity);
  return i === -1 ? SEVERITY_ORDER.length : i;
};
export const formatPct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
/** "L3–L7" for a range, "L7" for a single line. */
export const lineSpan = (start: number | null, end: number) =>
  start != null && start < end ? `L${start}–L${end}` : `L${end}`;
/** "850 ms", "2.3 s", "1m 05s". */
export function formatMs(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
}
