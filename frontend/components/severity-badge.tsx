import { Chip, type ChipTone } from "@/components/cr/review-chip";
import { cn } from "@/lib/utils";

/** Severity → chip tone: critical red, major orange, minor amber, nitpick muted. */
export const SEVERITY_TONE: Record<string, ChipTone> = {
  critical: "danger",
  major: "warn",
  minor: "caution",
  nitpick: "neutral",
};
export const SEVERITY_LABEL: Record<string, string> = {
  critical: "Critical",
  major: "Major",
  minor: "Minor",
  nitpick: "Nitpick",
};

export function SeverityBadge({ severity, className }: { severity: string; className?: string }) {
  return (
    <Chip tone={SEVERITY_TONE[severity] ?? "neutral"} className={cn(className)}>
      {SEVERITY_LABEL[severity] ?? severity}
    </Chip>
  );
}

const OUTLINE: Record<string, string> = {
  critical: "border-destructive/70 text-destructive",
  major: "border-primary/70 text-primary",
  minor: "border-caution/70 text-caution",
  nitpick: "border-border text-muted-foreground",
};

/** Outlined, unfilled severity chip ("High severity" in a red outline). The label is its own text node. */
export function SeverityOutline({ severity, className }: { severity: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 w-fit shrink-0 items-center gap-1 rounded-sm border px-2 text-xs font-medium whitespace-nowrap",
        OUTLINE[severity] ?? OUTLINE.nitpick,
        className,
      )}
    >
      {SEVERITY_LABEL[severity] ?? severity}{" "}
      <span className="font-normal opacity-90">severity</span>
    </span>
  );
}
