"use client";
import { Search } from "lucide-react";
import { type ComponentProps, type ComponentType, type ReactNode, useState } from "react";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Dropdown, type DropdownProps } from "@/components/cr/dropdown";
import { cn } from "@/lib/utils";

/** Search input with a leading magnifier (CodeRabbit table toolbar). */
export function SearchField({ className, ...props }: ComponentProps<"input">) {
  return (
    <div className={cn("relative w-full sm:w-64", className)}>
      <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input className="h-8 pl-8" {...props} />
    </div>
  );
}

/** Outline-button dropdown for toolbars (app-styled Dropdown with an optional leading icon). */
export function SelectButton({ className, ...props }: DropdownProps) {
  return <Dropdown className={cn("font-medium", className)} {...props} />;
}

/** Plain form select matching Input (for forms, not toolbars). */
export const fieldSelectClass =
  "h-8 rounded-md border border-input bg-subtle px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60";

/** Dashed empty state: muted icon, title, one sentence, optional CTA. */
export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon?: ComponentType<{ className?: string }>;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 rounded-md border border-dashed px-6 py-12 text-center", className)}>
      {Icon ? (
        <span className="mb-1 flex size-9 items-center justify-center rounded-md border bg-card">
          <Icon className="size-4 text-muted-foreground" />
        </span>
      ) : null}
      {title ? <p className="text-sm font-medium">{title}</p> : null}
      {children ? <div className="max-w-md text-sm text-muted-foreground">{children}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** Bordered section card with a 15px title, optional description and right-side action. */
export function SectionCard({
  title,
  description,
  action,
  children,
  flush,
  className,
  contentClassName,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  /** Content without side padding (tables). */
  flush?: boolean;
  className?: string;
  contentClassName?: string;
}) {
  return (
    <Card className={cn(flush && "pb-0", className)}>
      <CardHeader className={cn(flush && "border-b pb-4")}>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
        {action ? <CardAction>{action}</CardAction> : null}
      </CardHeader>
      <CardContent className={cn(flush && "px-0 [&_[data-slot=table-container]]:rounded-none [&_[data-slot=table-container]]:border-0", contentClassName)}>
        {children}
      </CardContent>
    </Card>
  );
}

/** Horizontal bars for a small categorical breakdown; hairline track, chart-token fill. */
export function BarList({ items, color = "var(--chart-1)" }: { items: { key: string; count: number }[]; color?: string }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  const total = items.reduce((a, i) => a + i.count, 0);
  if (items.length === 0) return <p className="py-6 text-center text-sm text-muted-foreground">No data for this period.</p>;
  return (
    <ul className="flex flex-col gap-3">
      {items.map((i) => (
        <li key={i.key} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate capitalize" title={i.key.replaceAll("_", " ")}>{i.key.replaceAll("_", " ")}</span>
          <span className="h-2 rounded-sm bg-subtle">
            <span className="block h-full rounded-sm" style={{ width: `${(i.count / max) * 100}%`, background: color }} />
          </span>
          <span className="min-w-12 text-right font-mono text-xs text-muted-foreground tabular-nums">
            {i.count}
            <span className="text-faint"> · {total ? Math.round((i.count / total) * 100) : 0}%</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function niceMax(n: number) {
  if (n <= 4) return 4;
  // Four equal, whole-number steps (0 · 15 · 30 · 45 · 60, like CodeRabbit's Daily Activity axis).
  const q = n / 4;
  const pow = 10 ** Math.floor(Math.log10(q));
  for (const s of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    const step = s * pow;
    if (Number.isInteger(step) && step >= q) return step * 4;
  }
  return 40 * pow;
}

/** Stacked daily columns with hairline gridlines and a y-axis; series colors are CSS colors (chart tokens). */
export function DailyColumns({
  points,
  series,
}: {
  points: { day: string; values: number[] }[];
  series: { label: string; color: string }[];
}) {
  const rawMax = Math.max(0, ...points.map((p) => p.values.reduce((a, b) => a + b, 0)));
  const max = niceMax(rawMax);
  const ticks = [max, (max * 3) / 4, max / 2, max / 4, 0];
  const fmtTick = (t: number) => (Number.isInteger(t) ? String(t) : t.toFixed(1));
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end gap-4 text-xs text-muted-foreground">
        {series.map((s) => (
          <span key={s.label} className="flex items-center gap-1.5">
            <span className="size-2 rounded-[2px]" style={{ background: s.color }} /> {s.label}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-[auto_1fr] gap-x-2">
        <div className="flex h-44 flex-col justify-between text-right font-mono text-[10px] leading-none text-faint tabular-nums">
          {ticks.map((t) => <span key={t} className="-translate-y-px">{fmtTick(t)}</span>)}
        </div>
        <div className="relative h-44">
          <div aria-hidden className="pointer-events-none absolute inset-0 flex flex-col justify-between">
            {ticks.map((t) => <span key={t} className="block h-px w-full bg-border/60" />)}
          </div>
          <div className="relative flex h-full items-end gap-[2px]" role="img" aria-label={`Daily ${series.map((s) => s.label).join(", ")}`}>
            {points.map((p) => {
              const total = p.values.reduce((a, b) => a + b, 0);
              return (
                <div
                  key={p.day}
                  className="group/col flex h-full min-w-0 flex-1 flex-col justify-end hover:bg-subtle"
                  title={`${p.day}: ${series.map((s, i) => `${s.label} ${p.values[i]}`).join(", ")}`}
                >
                  <div className="mx-auto flex w-full max-w-6 flex-col-reverse overflow-hidden rounded-t-[2px]" style={{ height: `${(total / max) * 100}%` }}>
                    {p.values.map((v, i) => (
                      <div key={i} className="w-full" style={{ height: total ? `${(v / total) * 100}%` : 0, background: series[i]?.color }} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <span />
        <div className="mt-2 flex justify-between font-mono text-[11px] text-faint">
          <span>{points[0]?.day}</span>
          <span>{points.at(-1)?.day}</span>
        </div>
      </div>
    </div>
  );
}

/** Bordered info strip above a chart ("Current refill rate: …" in CodeRabbit's Review Usage). */
export function InfoStrip({ title, caption, className }: { title: ReactNode; caption?: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-md border bg-card px-4 py-3.5 sm:px-5", className)}>
      <p className="text-base font-medium tracking-tight">{title}</p>
      {caption ? <p className="mt-1 text-sm text-muted-foreground">{caption}</p> : null}
    </div>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-09-30" → "Sep 30" (UTC day keys, no timezone drift). */
export function shortDay(day: string) {
  const [, m, d] = day.split("-").map(Number);
  return m && d ? `${MONTHS[m - 1]} ${d}` : day;
}

/**
 * Daily stacked bars in CodeRabbit's "Daily Activity" style: y-axis caption, hairline gridlines with
 * tick labels, spaced date labels, hover tooltip, and legend dots centred under the chart.
 * Series colors are CSS colors (chart tokens).
 */
export function DailyActivityChart({
  points,
  series,
  yLabel,
  className,
}: {
  points: { day: string; values: number[] }[];
  series: { label: string; color: string }[];
  yLabel?: string;
  className?: string;
}) {
  const rawMax = Math.max(0, ...points.map((p) => p.values.reduce((a, b) => a + b, 0)));
  const max = niceMax(rawMax);
  const ticks = [max, (max * 3) / 4, max / 2, max / 4, 0];
  const fmtTick = (t: number) => (Number.isInteger(t) ? String(t) : t.toFixed(1));
  const n = points.length;
  // ~8 labels on mobile widths, ~15 on desktop: every `step`-th day, anchored on the last day.
  const step = Math.max(1, Math.ceil(n / 15));
  const stepSm = Math.max(1, Math.ceil(n / 5));
  return (
    <div className={cn("flex flex-col", className)}>
      {yLabel ? <p className="mb-3 text-sm text-muted-foreground">{yLabel}</p> : null}
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3">
        <div className="relative h-56 w-8 text-right text-xs leading-none text-muted-foreground tabular-nums">
          {ticks.map((t, i) => (
            <span key={t} className="absolute right-0 -translate-y-1/2" style={{ top: `${(i / (ticks.length - 1)) * 100}%` }}>
              {fmtTick(t)}
            </span>
          ))}
        </div>
        <div className="relative h-56">
          <div aria-hidden className="pointer-events-none absolute inset-0">
            {ticks.map((t, i) => (
              <span
                key={t}
                className={cn("absolute inset-x-0 block h-px", i === ticks.length - 1 ? "bg-border" : "bg-border/60")}
                style={{ top: `${(i / (ticks.length - 1)) * 100}%` }}
              />
            ))}
          </div>
          {rawMax === 0 ? (
            <div className="absolute inset-0 z-10 flex items-center justify-center">
              <span className="rounded-md border border-dashed bg-background px-3 py-1.5 text-sm text-muted-foreground">
                No activity in this period
              </span>
            </div>
          ) : null}
          <div className="relative flex h-full items-end gap-[3px]" role="img" aria-label={`Daily ${series.map((s) => s.label).join(", ")}`}>
            {points.map((p, idx) => {
              const total = p.values.reduce((a, b) => a + b, 0);
              const right = idx > n / 2;
              return (
                <div key={p.day} className="group/col relative flex h-full min-w-0 flex-1 flex-col justify-end">
                  <span aria-hidden className="pointer-events-none absolute inset-y-0 left-1/2 hidden w-px bg-muted-foreground/50 group-hover/col:block" />
                  <div className="relative mx-auto flex w-full max-w-7 flex-col-reverse" style={{ height: `${(total / max) * 100}%` }}>
                    {p.values.map((v, i) => (
                      <div key={i} className="w-full" style={{ height: total ? `${(v / total) * 100}%` : 0, background: series[i]?.color }} />
                    ))}
                  </div>
                  <div
                    className={cn(
                      "pointer-events-none absolute top-6 z-10 hidden w-max max-w-56 rounded-md border bg-popover px-3 py-2 text-xs shadow-lg shadow-black/20 group-hover/col:block",
                      right ? "right-1/2 mr-2" : "left-1/2 ml-2",
                    )}
                  >
                    <p className="mb-1 text-sm font-medium text-popover-foreground">{shortDay(p.day)}</p>
                    {series.map((s, i) => (
                      <p key={s.label} className="flex items-center gap-2 text-muted-foreground">
                        <span className="size-2 rounded-[2px]" style={{ background: s.color }} />
                        {s.label}
                        <span className="ml-auto pl-3 text-popover-foreground tabular-nums">{p.values[i] ?? 0}</span>
                      </p>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <span />
        <div className="relative mt-2 flex h-4 gap-[3px] text-xs whitespace-nowrap text-muted-foreground">
          {points.map((p, idx) => {
            const fromEnd = n - 1 - idx;
            return (
              <span key={p.day} className="relative min-w-0 flex-1">
                {fromEnd % step === 0 ? (
                  <span className={cn(fromEnd === 0 ? "absolute right-0" : "absolute left-1/2 -translate-x-1/2", fromEnd % stepSm !== 0 && "max-sm:hidden", idx === 0 && fromEnd !== 0 && "hidden")}>
                    {shortDay(p.day)}
                  </span>
                ) : null}
              </span>
            );
          })}
        </div>
      </div>
      <div className="mt-5 flex flex-wrap justify-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
        {series.map((s) => (
          <span key={s.label} className="flex items-center gap-2">
            <span className="size-2.5 rounded-[2px]" style={{ background: s.color }} /> {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Client-side paging over already-loaded rows (resets to page 1 when the row set shrinks). */
export function usePaged<T>(rows: T[], initialSize = 10) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialSize);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const current = Math.min(page, pageCount);
  return {
    rows: rows.slice((current - 1) * pageSize, current * pageSize),
    page: current,
    pageCount,
    onPage: setPage,
    pageSize,
    onPageSize: (n: number) => {
      setPageSize(n);
      setPage(1);
    },
    /** Only worth a footer when there is more than one page at the smallest size. */
    paged: rows.length > initialSize,
  };
}

/** Skeleton of a MetricCard grid + chart, shaped like the dashboard so nothing jumps on load. */
export function DashboardSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <div className="flex flex-col" aria-busy="true" aria-label="Loading">
      <Skeleton className="mb-4 h-6 w-32" />
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
        {Array.from({ length: cards }, (_, i) => (
          <div key={i} className="rounded-lg border bg-card p-1.5">
            <Skeleton className="m-3.5 h-4 w-24" />
            <div className="flex flex-col gap-3 rounded-md bg-subtle p-4">
              <Skeleton className="h-7 w-16" />
              <Skeleton className="h-3.5 w-32 max-w-full" />
            </div>
          </div>
        ))}
      </div>
      <Skeleton className="mt-10 mb-4 h-6 w-36" />
      <Skeleton className="h-[4.5rem] w-full" />
      <Skeleton className="mt-5 h-64 w-full" />
    </div>
  );
}

/** Skeleton rows for a list/table while it loads. */
export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="flex flex-col" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 border-b py-4">
          <Skeleton className="size-4 shrink-0" />
          <Skeleton className="h-4 w-48 max-w-[40%]" />
          <Skeleton className="h-3.5 w-56 max-w-[30%]" />
          <Skeleton className="ml-auto size-4" />
        </div>
      ))}
    </div>
  );
}
