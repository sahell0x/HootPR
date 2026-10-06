"use client";
import { ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, X } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { TableHead } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { Dropdown } from "@/components/cr/dropdown";

/** Bordered segmented toggle ("My usage | Team usage", "Period 7 days | 30 days"). */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: readonly { value: T; label: ReactNode }[];
  label?: string;
  className?: string;
}) {
  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      {label ? <span className="text-sm text-muted-foreground">{label}</span> : null}
      <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border bg-card p-0.5">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={o.value === value}
            onClick={() => onChange(o.value)}
            className={cn(
              "h-7 rounded-[5px] px-3 text-sm text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60",
              o.value === value && "bg-accent font-medium text-foreground",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Metric card: titled outer frame with a darker inner panel holding the big number (Review Usage "Key Metrics"). */
export function MetricCard({ title, value, caption, className }: { title: ReactNode; value: ReactNode; caption?: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border bg-card p-1", className)}>
      <p className="px-4 pt-3 pb-3 text-[0.9375rem] font-medium">{title}</p>
      <div className="rounded-md bg-accent/60 px-4 py-4 dark:bg-[#232127]">
        <p className="text-3xl font-medium tracking-tight tabular-nums">{value}</p>
        {caption ? <p className="mt-2 text-sm text-muted-foreground">{caption}</p> : null}
      </div>
    </div>
  );
}

export function MetricGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-3", className)}>{children}</div>;
}

export function SectionTitle({ children, className, action }: { children: ReactNode; className?: string; action?: ReactNode }) {
  return (
    <div className={cn("mt-8 mb-4 flex items-center justify-between gap-3 first:mt-0", className)}>
      <h2 className="text-lg font-medium tracking-tight">{children}</h2>
      {action}
    </div>
  );
}

/** Table header cell with the sort affordance CodeRabbit shows on every sortable column. */
export function SortableHead({
  children,
  sorted,
  onSort,
  className,
  ...props
}: ComponentProps<typeof TableHead> & { sorted?: "asc" | "desc" | false; onSort?: () => void }) {
  return (
    <TableHead className={className} aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined} {...props}>
      <button type="button" onClick={onSort} className="inline-flex items-center gap-1.5 hover:text-foreground rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
        {children}
        <ArrowUpDown className={cn("size-3.5", sorted ? "text-foreground" : "text-faint")} aria-hidden />
      </button>
    </TableHead>
  );
}

/** "Rows per page [10 ⌄]   Page 1 of N  « ‹ › »" footer. */
export function TablePagination({
  page,
  pageCount,
  onPage,
  pageSize,
  onPageSize,
  sizes = [10, 20, 50],
  className,
}: {
  page: number;
  pageCount: number;
  onPage: (p: number) => void;
  pageSize?: number;
  onPageSize?: (n: number) => void;
  sizes?: number[];
  className?: string;
}) {
  const last = Math.max(1, pageCount);
  return (
    <div className={cn("mt-3 flex flex-wrap items-center justify-end gap-x-6 gap-y-2 text-sm", className)}>
      {pageSize && onPageSize ? (
        <label className="flex items-center gap-2 text-muted-foreground">
          Rows per page
          <span className="relative">
            <Dropdown aria-label="Rows per page" value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))} className="w-[72px]">
              {sizes.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Dropdown>
          </span>
        </label>
      ) : null}
      <span className="tabular-nums">
        Page {Math.min(page, last)} of {last}
      </span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon-sm" aria-label="First page" disabled={page <= 1} onClick={() => onPage(1)}>
          <ChevronsLeft />
        </Button>
        <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft />
        </Button>
        <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={page >= last} onClick={() => onPage(page + 1)}>
          <ChevronRight />
        </Button>
        <Button variant="outline" size="icon-sm" aria-label="Last page" disabled={page >= last} onClick={() => onPage(last)}>
          <ChevronsRight />
        </Button>
      </div>
    </div>
  );
}

/** Floating bottom-center bulk action bar ("4 Selected   [Install] [Uninstall]"). */
export function BulkBar({ count, onClear, children }: { count: number; onClear?: () => void; children: ReactNode }) {
  if (count <= 0) return null;
  return (
    <div className="fixed inset-x-0 bottom-6 z-40 flex justify-center px-4">
      <div className="flex w-full max-w-md items-center gap-3 rounded-lg border bg-popover px-4 py-2.5 shadow-2xl shadow-black/40">
        <span className="text-sm">{count} Selected</span>
        {onClear ? (
          <button type="button" aria-label="Clear selection" onClick={onClear} className="text-muted-foreground hover:text-foreground">
            <X className="size-4" aria-hidden />
          </button>
        ) : null}
        <div className="ml-auto flex items-center gap-2">{children}</div>
      </div>
    </div>
  );
}

/** Outlined filter trigger: "User: All ⌄". Wrap a native select so behaviour stays simple and accessible. */
export function FilterSelect({
  label,
  value,
  onChange,
  options,
  className,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: readonly { value: string; label: string }[];
  className?: string;
}) {
  const current = options.find((o) => o.value === value)?.label ?? value;
  return (
    <label className={cn("relative inline-flex h-8 items-center gap-1 rounded-md border bg-card pr-2 pl-3 text-sm hover:bg-accent", className)}>
      <span className="text-muted-foreground">{label}:</span>
      <span>{current}</span>
      <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
      <Dropdown aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="absolute inset-0 h-auto cursor-pointer border-0 opacity-0">
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Dropdown>
    </label>
  );
}

/** Outlined status pill with a leading dot, as in CodeRabbit's seat/status columns. */
export function StatusPill({ tone = "neutral", children, dot = true }: { tone?: "neutral" | "primary" | "success" | "warning" | "danger"; children: ReactNode; dot?: boolean }) {
  const tones = {
    neutral: "border-border text-muted-foreground [--dot:var(--faint)]",
    primary: "border-primary/40 text-primary [--dot:var(--primary)]",
    success: "border-success/40 text-success [--dot:var(--success)]",
    warning: "border-caution/40 text-caution [--dot:var(--caution)]",
    danger: "border-destructive/40 text-destructive [--dot:var(--destructive)]",
  } as const;
  return (
    <span className={cn("inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-xs font-medium whitespace-nowrap", tones[tone])}>
      {dot ? <span className="size-1.5 rounded-full bg-(--dot)" aria-hidden /> : null}
      {children}
    </span>
  );
}
