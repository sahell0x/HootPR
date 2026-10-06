"use client";
import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { Dropdown } from "@/components/cr/dropdown";

export const selectClass =
  "h-8 rounded-md border border-input bg-card px-2 text-[13px] text-foreground transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function PageTitle({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-medium tracking-tight">{children}</h1>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function DaysSelect({ value, onChange }: { value: number; onChange: (d: number) => void }) {
  return (
    <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
      Period
      <Dropdown value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {[7, 30, 90, 365].map((d) => (
          <option key={d} value={d}>
            Last {d} days
          </option>
        ))}
      </Dropdown>
    </label>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 p-4">
        <span className="eyebrow">{label}</span>
        <span className="text-2xl font-medium tracking-tight tabular-nums">{value}</span>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </CardContent>
    </Card>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">{children}</div>;
}

/** Horizontal bars for a small categorical breakdown. */
export function BarList({ items, tone = "bg-chart-1" }: { items: { key: string; count: number }[]; tone?: string }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No data for this period.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {items.map((i) => (
        <li key={i.key} className="grid grid-cols-[7rem_1fr_3rem] items-center gap-2 text-sm">
          <span className="truncate capitalize">{i.key.replaceAll("_", " ")}</span>
          <span className="h-2 rounded-sm bg-muted">
            <span className={cn("block h-full rounded-sm", tone)} style={{ width: `${(i.count / max) * 100}%` }} />
          </span>
          <span className="text-right tabular-nums">{i.count}</span>
        </li>
      ))}
    </ul>
  );
}

/** Daily columns; each series is stacked bottom-up. */
export function DailyColumns({
  points,
  series,
}: {
  points: { day: string; values: number[] }[];
  series: { label: string; tone: string }[];
}) {
  const max = Math.max(1, ...points.map((p) => p.values.reduce((a, b) => a + b, 0)));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-40 items-end gap-px" role="img" aria-label={`Daily ${series.map((s) => s.label).join(", ")}`}>
        {points.map((p) => {
          const total = p.values.reduce((a, b) => a + b, 0);
          return (
            <div
              key={p.day}
              className="flex min-w-0 flex-1 flex-col-reverse rounded-t-sm hover:opacity-80"
              style={{ height: `${(total / max) * 100}%` }}
              title={`${p.day}: ${series.map((s, i) => `${s.label} ${p.values[i]}`).join(", ")}`}
            >
              {p.values.map((v, i) => (
                <div key={i} className={cn(series[i]?.tone, "w-full")} style={{ height: total ? `${(v / total) * 100}%` : 0 }} />
              ))}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{points[0]?.day}</span>
        <span className="flex gap-3">
          {series.map((s) => (
            <span key={s.label} className="flex items-center gap-1">
              <span className={cn("size-2 rounded-sm", s.tone)} /> {s.label}
            </span>
          ))}
        </span>
        <span>{points.at(-1)?.day}</span>
      </div>
    </div>
  );
}

export function formatDuration(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} d`;
}

export const fmtInt = (n: number) => n.toLocaleString("en-US");
