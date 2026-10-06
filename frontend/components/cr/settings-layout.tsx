"use client";
import { ArrowLeft, ChevronUp, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { SettingsSelect } from "@/components/cr/settings-select";
import { SidebarOverride, TopbarTitle } from "@/components/cr/shell-slots";
import { cn } from "@/lib/utils";

export interface SettingsNavItem {
  id: string;
  label: string;
  icon?: LucideIcon;
  children?: SettingsNavItem[];
}

export interface SettingsNavGroup {
  heading: string;
  items: SettingsNavItem[];
}

export type SettingsMode = "concise" | "all" | "yaml";

export const SETTINGS_MODES: readonly { value: SettingsMode; label: string }[] = [
  { value: "concise", label: "Concise" },
  { value: "all", label: "All Settings" },
  { value: "yaml", label: "YAML Editor" },
];

/** Stable DOM id for a settings section ("Path filters & instructions" → "settings-path-filters-instructions"). */
export const sectionId = (label: string) =>
  `settings-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`;

const flatten = (items: SettingsNavItem[]): SettingsNavItem[] =>
  items.flatMap((i) => [i, ...flatten(i.children ?? [])]);

/**
 * Labels are drawn from `data-label` (CSS generated content) so the navigation never duplicates the
 * visible section titles in the DOM text tree (tests and find-in-page hit the section, not the nav).
 */
function NavLabel({ label, className }: { label: string; className?: string }) {
  return <span aria-hidden data-label={label} className={cn("truncate before:content-[attr(data-label)]", className)} />;
}

function ModeSelect({ mode, onMode, className }: { mode: SettingsMode; onMode: (m: SettingsMode) => void; className?: string }) {
  return (
    <label className={cn("flex items-center gap-2 text-[13px] whitespace-nowrap text-muted-foreground", className)}>
      Change mode:
      <SettingsSelect aria-label="Change mode" value={mode} wrapperClassName="w-auto flex-1"
        className="h-8 min-w-0 bg-card text-[13px] text-foreground"
        onChange={(e) => onMode(e.target.value as SettingsMode)}>
        {SETTINGS_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
      </SettingsSelect>
    </label>
  );
}

/**
 * Settings frame in the style of CodeRabbit's settings mode: the app sidebar is taken over by
 * "← Back", the section tree and a "Change mode" select; the top bar shows the current section.
 * Outside the shell (unit tests) those slots render nothing and only the content is shown. On small
 * screens a compact horizontal section picker replaces the sidebar.
 */
export function SettingsLayout({ groups, children, backHref, mode, onModeChange }: {
  groups: SettingsNavGroup[];
  children: ReactNode;
  backHref: string;
  mode: SettingsMode;
  onModeChange: (m: SettingsMode) => void;
}) {
  const visible = groups.filter((g) => g.items.length);
  const items = useMemo(() => flatten(visible.flatMap((g) => g.items)), [visible]);
  const [active, setActive] = useState<string | undefined>(items[0]?.id);
  const ids = items.map((i) => i.id).join("|");
  /** While a click-triggered smooth scroll runs, keep the clicked section active. */
  const lockUntil = useRef(0);

  useEffect(() => {
    const list = ids.split("|").filter(Boolean);
    const onScroll = () => {
      if (Date.now() < lockUntil.current) return;
      let current = list[0];
      for (const id of list) {
        const el = document.getElementById(id);
        if (el && el.offsetParent !== null && el.getBoundingClientRect().top <= 140) current = id;
      }
      if (window.scrollY > 0 && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
        const last = [...list].reverse().find((id) => document.getElementById(id)?.offsetParent != null);
        if (last) current = last;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [ids]);

  const go = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el instanceof HTMLDetailsElement) el.open = true;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(null, "", `#${id}`);
    lockUntil.current = Date.now() + 900;
    setActive(id);
  };

  const activeItem = items.find((i) => i.id === active) ?? items[0];

  const link = (i: SettingsNavItem, child = false) => {
    const on = active === i.id;
    const Icon = i.icon;
    return (
      <a
        href={`#${i.id}`}
        aria-label={i.label}
        aria-current={on ? "location" : undefined}
        onClick={(e) => { e.preventDefault(); go(i.id); }}
        className={cn(
          "flex h-8 min-w-0 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] transition-colors",
          "focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none",
          on ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
            : child ? "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
              : "text-sidebar-foreground/90 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
        )}
      >
        {Icon ? <Icon aria-hidden className={cn("size-4 shrink-0", on ? "text-foreground" : "text-muted-foreground")} /> : null}
        <NavLabel label={i.label} className="min-w-0 flex-1" />
        {i.children?.length ? <ChevronUp aria-hidden className="size-3.5 shrink-0 text-muted-foreground" /> : null}
      </a>
    );
  };

  const sidebar = (
    <nav aria-label="Settings sections" className="flex min-h-0 flex-1 flex-col">
      <div className="p-2">
        <Link href={backHref}
          className="flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-foreground">
          <ArrowLeft aria-hidden className="size-4" /> Back
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {visible.map((g, gi) => (
          <div key={g.heading} className={cn(gi > 0 && "mt-4")}>
            {visible.length > 1 ? <p className="mb-1 px-2.5 text-xs text-faint">{g.heading}</p> : null}
            <ul className="flex flex-col gap-0.5">
              {g.items.map((i) => (
                <li key={i.id}>
                  {link(i)}
                  {i.children?.length ? (
                    <ul className="mt-0.5 ml-[1.1rem] flex flex-col gap-0.5 border-l border-sidebar-border pl-2">
                      {i.children.map((c) => <li key={c.id}>{link(c, true)}</li>)}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-sidebar-border p-3">
        <ModeSelect mode={mode} onMode={onModeChange} />
      </div>
    </nav>
  );

  return (
    <>
      <SidebarOverride>{sidebar}</SidebarOverride>
      {activeItem ? <TopbarTitle><NavLabel label={activeItem.label} /></TopbarTitle> : null}
      <div className="mb-5 flex flex-col gap-3 md:hidden">
        <div aria-label="Settings sections" role="navigation"
          className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
          {items.map((i) => {
            const on = active === i.id;
            return (
              <a key={i.id} href={`#${i.id}`} aria-label={i.label} aria-current={on ? "location" : undefined}
                onClick={(e) => { e.preventDefault(); go(i.id); }}
                className={cn(
                  "flex h-8 shrink-0 items-center rounded-md border px-2.5 text-[13px] whitespace-nowrap transition-colors",
                  on ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-subtle hover:text-foreground",
                )}>
                <NavLabel label={i.label} />
              </a>
            );
          })}
        </div>
        <ModeSelect mode={mode} onMode={onModeChange} />
      </div>
      <div className="flex min-w-0 flex-col gap-6">{children}</div>
    </>
  );
}

/**
 * Bordered settings card. Default: 15px title + muted description header, body, optional bg-subtle
 * footer. `split` puts the title/description in a left column and the fields on the right.
 */
export function SettingsSection({ id, title, description, action, footer, children, className, bodyClassName, split = false }: {
  id?: string;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  split?: boolean;
}) {
  const hasBody = children !== undefined && children !== null;
  if (split)
    return (
      <section id={id} className={cn("scroll-mt-20 overflow-hidden rounded-md border bg-card text-sm", className)}>
        <div className="grid gap-4 px-5 py-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-8">
          <header className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[0.9375rem] leading-snug font-medium tracking-tight">{title}</h2>
              {action}
            </div>
            {description ? <div className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{description}</div> : null}
          </header>
          {hasBody ? <div className={cn("min-w-0", bodyClassName)}>{children}</div> : null}
        </div>
        {footer ? (
          <footer className="flex flex-wrap items-center justify-end gap-3 border-t bg-subtle px-5 py-3">{footer}</footer>
        ) : null}
      </section>
    );
  return (
    <section id={id} className={cn("scroll-mt-20 overflow-hidden rounded-md border bg-card text-sm", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-[0.9375rem] leading-snug font-medium tracking-tight">{title}</h2>
          {description ? <div className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{description}</div> : null}
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </header>
      {hasBody ? <div className={cn("px-5 py-4", bodyClassName)}>{children}</div> : null}
      {footer ? (
        <footer className="flex flex-wrap items-center justify-end gap-3 border-t bg-subtle px-5 py-3">{footer}</footer>
      ) : null}
    </section>
  );
}

/** One settings row: label + muted description on the left, the control on the right. */
export function SettingsRow({ label, description, children, className, stack = false }: {
  label: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Put the control under the label (wide editors such as textareas and lists). */
  stack?: boolean;
}) {
  return (
    <div className={cn(
      "flex flex-col gap-3 px-4 py-3.5",
      !stack && "sm:flex-row sm:items-center sm:justify-between sm:gap-8",
      className,
    )}>
      <div className="min-w-0 sm:max-w-md">
        <div className="text-sm font-medium">{label}</div>
        {description ? <div className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{description}</div> : null}
      </div>
      <div className={cn("min-w-0", !stack && "sm:shrink-0")}>{children}</div>
    </div>
  );
}
