import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Bordered metric tile: uppercase mono label over a large value, optional hint underneath. */
export function StatTile({
  label,
  value,
  hint,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-md border bg-card px-4 py-3", className)}>
      <p className="eyebrow">{label}</p>
      <p className="mt-1 text-2xl font-medium tracking-tight tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function StatGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4", className)}>{children}</div>;
}
