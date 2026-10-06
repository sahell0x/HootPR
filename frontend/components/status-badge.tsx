import { Chip, type ChipTone } from "@/components/cr/review-chip";
import type { ReviewStatus } from "@/lib/api-types";
import { STATUS_LABEL } from "@/lib/format";

const TONE: Record<ReviewStatus, ChipTone> = {
  queued: "neutral",
  running: "info",
  completed: "success",
  failed: "danger",
  skipped: "faint",
  rate_limited: "caution",
  no_credits: "warn",
};

export function StatusBadge({ status }: { status: ReviewStatus }) {
  return (
    <Chip tone={TONE[status]} pulse={status === "running" || status === "queued"}>
      {STATUS_LABEL[status]}
    </Chip>
  );
}

const DOT: Record<ReviewStatus, string> = {
  queued: "bg-muted-foreground",
  running: "bg-chart-3",
  completed: "bg-success",
  failed: "bg-destructive",
  skipped: "bg-faint",
  rate_limited: "bg-caution",
  no_credits: "bg-primary",
};

/** Plain "● Completed" outcome (dot + label), as in CodeRabbit's Review Log tables. */
export function StatusOutcome({ status, title }: { status: ReviewStatus; title?: string }) {
  const live = status === "running" || status === "queued";
  return (
    <span title={title} className="inline-flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${DOT[status]}${live ? " animate-pulse" : ""}`} />
      {STATUS_LABEL[status]}
    </span>
  );
}
