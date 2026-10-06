import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Semantic tones for the small rectangular review chips (CodeRabbit "● P1" style). */
export type ChipTone = "danger" | "warn" | "caution" | "success" | "info" | "neutral" | "faint";

const TONE: Record<ChipTone, { chip: string; dot: string }> = {
  danger: { chip: "border-destructive/30 bg-destructive/10 text-destructive", dot: "bg-destructive" },
  warn: { chip: "border-primary/30 bg-primary/10 text-primary", dot: "bg-primary" },
  caution: { chip: "border-caution/30 bg-caution/10 text-caution", dot: "bg-caution" },
  success: { chip: "border-success/30 bg-success/10 text-success", dot: "bg-success" },
  info: { chip: "border-chart-3/35 bg-chart-3/10 text-chart-3", dot: "bg-chart-3" },
  neutral: { chip: "border-border bg-subtle text-muted-foreground", dot: "bg-muted-foreground" },
  faint: { chip: "border-border bg-transparent text-faint", dot: "bg-faint" },
};

/** Rounded-sm, 1px-bordered, tinted chip with an optional leading status dot. */
export function Chip({
  tone = "neutral",
  dot = true,
  pulse = false,
  mono = false,
  className,
  title,
  children,
}: {
  tone?: ChipTone;
  dot?: boolean;
  pulse?: boolean;
  mono?: boolean;
  className?: string;
  title?: string;
  children: ReactNode;
}) {
  const t = TONE[tone];
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 w-fit shrink-0 items-center gap-1.5 rounded-sm border px-1.5 text-xs font-medium whitespace-nowrap",
        mono && "font-mono text-[0.6875rem]",
        t.chip,
        className,
      )}
    >
      {dot ? (
        <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", t.dot, pulse && "animate-pulse")} />
      ) : null}
      {children}
    </span>
  );
}

/** Plain outline tag (category, focus area, source) — muted, no dot. */
export function Tag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 w-fit shrink-0 items-center rounded-sm border px-1.5 text-[0.6875rem] text-muted-foreground whitespace-nowrap",
        className,
      )}
    >
      {children}
    </span>
  );
}
