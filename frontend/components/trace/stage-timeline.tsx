import { Chip } from "@/components/cr/review-chip";
import type { ReviewStage } from "@/lib/api-types";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

const DOT: Record<ReviewStage["status"], string> = {
  ok: "border-success bg-success/20", degraded: "border-caution bg-caution/25",
  failed: "border-destructive bg-destructive/25", skipped: "border-faint bg-transparent",
};
const BAR: Record<ReviewStage["status"], string> = {
  ok: "bg-success/60", degraded: "bg-caution/70", failed: "bg-destructive/70", skipped: "bg-faint/50",
};
const CHIP = { degraded: "caution", failed: "danger", skipped: "faint" } as const;

export function StageTimeline({ stages }: { stages: ReviewStage[] }) {
  if (stages.length === 0) return <p className="py-4 text-sm text-muted-foreground">No stages recorded.</p>;
  const max = Math.max(...stages.map((s) => s.duration_ms), 1);
  const total = stages.reduce((a, s) => a + s.duration_ms, 0);
  return (
    <div className="rounded-md border bg-subtle px-4 py-3">
      <ol aria-label="Pipeline stages" className="flex flex-col">
        {stages.map((s, i) => (
          <li key={`${s.name}-${i}`} className="relative grid grid-cols-[1rem_6rem_minmax(0,1fr)_4rem] gap-x-3 pb-2.5 last:pb-0 sm:grid-cols-[1rem_8rem_minmax(0,1fr)_5rem]">
            {/* hairline connector */}
            {i < stages.length - 1 ? (
              <span aria-hidden className="absolute top-3.5 bottom-0 left-[0.4375rem] w-px bg-border" />
            ) : null}
            <span aria-hidden className={cn("relative z-10 mt-1 size-2.5 justify-self-center rounded-full border", DOT[s.status])} />
            <span className="truncate font-mono text-[0.8125rem] leading-[1.125rem]">{s.name}</span>
            <div className="flex min-w-0 flex-col gap-1 pt-[0.4375rem]">
              <div className="h-1 w-full overflow-hidden rounded-full bg-subtle">
                <div className={cn("h-1 rounded-full", BAR[s.status])} style={{ width: `${Math.max(1.5, (s.duration_ms / max) * 100)}%` }} />
              </div>
              {s.detail || s.status !== "ok" ? (
                <div className="flex min-w-0 items-center gap-2">
                  {s.status !== "ok" ? <Chip tone={CHIP[s.status]} mono>{s.status}</Chip> : null}
                  {s.detail ? <span className="truncate text-xs text-muted-foreground">{s.detail}</span> : null}
                </div>
              ) : null}
            </div>
            <span className="text-right font-mono text-xs leading-[1.125rem] text-muted-foreground tabular-nums">{formatMs(s.duration_ms)}</span>
          </li>
        ))}
      </ol>
      <div className="mt-3 flex justify-between border-t pt-2.5 font-mono text-xs text-muted-foreground">
        <span className="eyebrow">Total</span>
        <span className="text-foreground tabular-nums">{formatMs(total)}</span>
      </div>
    </div>
  );
}
