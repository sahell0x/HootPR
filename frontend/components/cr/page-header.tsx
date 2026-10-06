import { Info } from "lucide-react";
import type { ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** Page title row: 24px medium title (+ optional info tooltip), muted one-liner, actions on the right. */
export function PageHeader({
  title,
  description,
  info,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  info?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-6 flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-2xl font-medium tracking-tight">
          {title}
          {info ? (
            <Tooltip>
              <TooltipTrigger aria-label="About this page" className="text-muted-foreground hover:text-foreground">
                <Info className="size-4" aria-hidden />
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">{info}</TooltipContent>
            </Tooltip>
          ) : null}
        </h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Centered content column used by list pages (Repositories, API keys, Learnings…). */
export function PageContainer({ children, className, wide = false }: { children: ReactNode; className?: string; wide?: boolean }) {
  return <div className={cn("mx-auto w-full", wide ? "max-w-7xl" : "max-w-6xl", className)}>{children}</div>;
}
