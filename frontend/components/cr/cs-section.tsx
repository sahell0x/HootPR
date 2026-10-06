"use client";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Collapsible page section ("⌄ Approach", "› Research", "› Assumptions [2]"): chevron + 18px medium heading,
 * optional count badge, content in a bordered rounded-lg card. Content is unmounted while collapsed.
 */
export function CollapsibleSection({
  id,
  title,
  icon,
  count,
  open,
  onOpenChange,
  actions,
  bare = false,
  className,
  bodyClassName,
  children,
}: {
  id: string;
  title: ReactNode;
  icon?: ReactNode;
  count?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  actions?: ReactNode;
  /** Render the content without the bordered card (content brings its own frames). */
  bare?: boolean;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <section id={id} aria-labelledby={`${id}-h`} className={cn("flex scroll-mt-20 flex-col gap-3", className)}>
      <div className="flex min-h-8 items-center justify-between gap-3">
        <h2 id={`${id}-h`} className="min-w-0 flex-1">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={`${id}-body`}
            onClick={() => onOpenChange(!open)}
            className="group -ml-1 inline-flex max-w-full items-center gap-2 rounded-md px-1 py-0.5 text-lg font-medium tracking-tight focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <Chevron className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" aria-hidden />
            {icon}
            <span className="text-left">{title}</span>
            {count != null ? (
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm bg-muted px-1.5 font-mono text-xs font-normal text-muted-foreground tabular-nums">
                {count}
              </span>
            ) : null}
          </button>
        </h2>
        {actions && open ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
      {open ? (
        <div id={`${id}-body`} className={cn(!bare && "rounded-lg border bg-card", bodyClassName)}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

/** Line-tab strip that jumps to (and expands) a page section, GitHub "Conversation | Files changed" style. */
export function SectionTabs<T extends string>({
  label,
  items,
  active,
  onSelect,
  className,
}: {
  label: string;
  items: readonly { id: T; label: ReactNode; count?: number }[];
  active: T | null;
  onSelect: (id: T) => void;
  className?: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={cn("flex w-full gap-5 overflow-x-auto overflow-y-hidden border-b [scrollbar-width:none]", className)}>
      {items.map((it) => {
        const on = it.id === active;
        return (
          <button
            key={it.id}
            type="button"
            role="tab"
            aria-selected={on}
            aria-controls={it.id}
            onClick={() => onSelect(it.id)}
            className={cn(
              "relative inline-flex h-10 shrink-0 items-center gap-1.5 px-0.5 text-sm whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              on && "text-foreground after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-primary",
            )}
          >
            {it.label}
            {it.count != null ? (
              <span aria-hidden className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 font-mono text-[0.6875rem] text-muted-foreground tabular-nums">
                {it.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Height for a `sticky top-0` side panel so it fills the visible viewport below whatever sits above it
 * (banner, top bar) and never runs past the bottom edge. Returns a callback ref for the panel and its pixel height.
 */
export function useViewportFill<E extends HTMLElement>() {
  const [el, setEl] = useState<E | null>(null);
  const [height, setHeight] = useState<number | null>(null);
  useEffect(() => {
    if (!el) return;
    let raf = 0;
    const measure = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const top = Math.max(0, el.getBoundingClientRect().top);
        setHeight(Math.max(320, Math.round(window.innerHeight - top)));
      });
    };
    measure();
    window.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
    };
  }, [el]);
  return { ref: setEl, height };
}
