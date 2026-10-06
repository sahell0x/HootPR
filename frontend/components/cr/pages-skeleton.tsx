import { TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Loading placeholder shaped like a bordered data table (header row + N body rows), so the page
 * does not jump when the real table replaces it.
 */
export function TableSkeleton({ cols = 4, rows = 5, rowHeight = "h-14", className }: {
  cols?: number; rows?: number; rowHeight?: string; className?: string;
}) {
  return (
    <div aria-busy="true" aria-label="Loading" className={cn("overflow-hidden rounded-md border bg-card", className)}>
      <div className="flex h-10 items-center gap-6 border-b bg-subtle px-4">
        {Array.from({ length: cols }, (_, i) => (
          <Skeleton key={i} className={cn("h-3", i === 0 ? "w-24 flex-[2]" : "w-16 flex-1")} />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className={cn("flex items-center gap-6 border-b px-4 last:border-b-0", rowHeight)}>
          {Array.from({ length: cols }, (_, i) => (
            <Skeleton key={i} className={cn("h-3.5", i === 0 ? "flex-[2]" : "flex-1")} style={{ maxWidth: i === 0 ? `${60 + ((r * 13) % 30)}%` : undefined }} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Inline load error for a section (not the whole page): message + optional Retry. */
export function SectionError({ title = "Could not load this section.", error, onRetry, className }: {
  title?: ReactNode; error?: Error | null; onRetry?: () => void; className?: string;
}) {
  return (
    <div role="alert" className={cn("flex flex-col items-center justify-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-6 py-10 text-center", className)}>
      <span className="mb-1 flex size-9 items-center justify-center rounded-md border border-destructive/30 bg-card">
        <TriangleAlert aria-hidden className="size-4 text-destructive" />
      </span>
      <p className="text-sm font-medium">{title}</p>
      {error?.message ? <p className="max-w-md text-sm text-muted-foreground">{error.message}</p> : null}
      {onRetry ? <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>Try again</Button> : null}
    </div>
  );
}
