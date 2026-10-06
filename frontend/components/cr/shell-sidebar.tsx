"use client";
import { BookOpen, ChevronDown, PanelLeftClose, PanelLeftOpen, TriangleAlert, Zap } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { OwlMark } from "@/components/brand";
import { OrgSwitcher } from "@/components/org-switcher";
import type { Org } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { DOCS_URL, isActive, NAV_ITEMS, ORG_SETTINGS, ORG_SETTINGS_ITEMS } from "./shell-nav";

const itemCls =
  "flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none";
const activeCls = "bg-sidebar-accent font-medium text-sidebar-accent-foreground hover:bg-sidebar-accent";

/**
 * The app sidebar: org header row, flat nav (or a page's SidebarOverride), credits card, docs, collapse.
 * `rail` = desktop icon-only mode (56px); on mobile the sidebar is always full width inside the drawer.
 */
export function ShellSidebar({
  org,
  pathname,
  credits,
  outOfCredits = false,
  override,
  rail,
  onToggleRail,
}: {
  org: Org;
  pathname: string;
  credits: string;
  /** Balance is zero: the card turns into a warning (reviews are paused until a top-up). */
  outOfCredits?: boolean;
  override: ReactNode | null;
  rail: boolean;
  onToggleRail: () => void;
}) {
  const base = `/o/${org.slug}`;
  const settingsActive = ORG_SETTINGS_ITEMS.some((i) => isActive(pathname, `${base}/${i.href}`));
  const [settingsOpen, setSettingsOpen] = useState(settingsActive);
  useEffect(() => {
    if (settingsActive) setSettingsOpen(true);
  }, [settingsActive]);
  const label = cn(rail && "md:sr-only");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <OrgSwitcher current={org.slug} provider={org.provider} collapsed={rail} />

      {override ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{override}</div>
      ) : (
        <>
          <nav aria-label="Organization" className={cn("flex flex-1 flex-col gap-0.5 overflow-y-auto p-2", rail && "md:items-center")}>
            {NAV_ITEMS.map(({ href, label: text, icon: Icon }) => {
              const to = `${base}/${href}`;
              const active = isActive(pathname, to);
              return (
                <Link
                  key={href}
                  href={to}
                  title={rail ? text : undefined}
                  aria-current={active ? "page" : undefined}
                  className={cn(itemCls, active && activeCls, rail && "md:size-8 md:justify-center md:px-0")}
                >
                  <Icon className={cn("size-4 shrink-0", active && "text-foreground")} aria-hidden />
                  <span className={cn("truncate", label)}>{text}</span>
                </Link>
              );
            })}

            {rail ? (
              <Link
                href={`${base}/settings`}
                title={ORG_SETTINGS.label}
                aria-current={settingsActive ? "page" : undefined}
                className={cn(itemCls, settingsActive && activeCls, "hidden md:flex md:size-8 md:justify-center md:px-0")}
              >
                <ORG_SETTINGS.icon className="size-4 shrink-0" aria-hidden />
                <span className="sr-only">{ORG_SETTINGS.label}</span>
              </Link>
            ) : null}
            <div className={cn(rail && "md:hidden")}>
              <button
                type="button"
                aria-expanded={settingsOpen}
                onClick={() => setSettingsOpen((v) => !v)}
                className={cn(itemCls, settingsActive && !settingsOpen && activeCls)}
              >
                <ORG_SETTINGS.icon className={cn("size-4 shrink-0", settingsActive && "text-foreground")} aria-hidden />
                <span className="flex-1 truncate text-left">{ORG_SETTINGS.label}</span>
                <ChevronDown
                  className={cn("size-3.5 shrink-0 transition-transform", settingsOpen && "rotate-180")}
                  aria-hidden
                />
              </button>
              {settingsOpen ? (
                <div className="mt-0.5 flex flex-col gap-0.5">
                  {ORG_SETTINGS_ITEMS.map(({ href, label: text }) => {
                    const to = `${base}/${href}`;
                    const active = isActive(pathname, to);
                    return (
                      <Link
                        key={href}
                        href={to}
                        aria-current={active ? "page" : undefined}
                        className={cn(itemCls, "pl-8.5", active && activeCls)}
                      >
                        <span className="truncate">{text}</span>
                      </Link>
                    );
                  })}
                </div>
              ) : null}
            </div>
          </nav>

          <div className={cn("flex flex-col gap-1 p-2", rail && "md:items-center")}>
            <Link
              href={`${base}/billing`}
              title={rail ? `${credits} credits left` : undefined}
              data-state={outOfCredits ? "empty" : undefined}
              className={cn(
                "group flex flex-col gap-0.5 rounded-md border px-2.5 py-2 text-[13px] transition-colors focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none",
                outOfCredits
                  ? "border-destructive/40 bg-destructive/10 hover:bg-destructive/15"
                  : "border-sidebar-border bg-background/40 hover:border-border hover:bg-sidebar-accent/40",
                rail && "md:size-8 md:items-center md:justify-center md:p-0",
              )}
            >
              <span className="flex items-center gap-2 font-medium text-sidebar-foreground">
                {outOfCredits ? (
                  <TriangleAlert className="size-3.5 shrink-0 text-destructive" aria-hidden />
                ) : (
                  <Zap className="size-3.5 shrink-0 text-primary" aria-hidden />
                )}
                <span className={label}>
                  <span className="font-mono tabular-nums">{credits}</span> credits left
                </span>
              </span>
              <span className={cn("pl-5.5 text-xs text-muted-foreground", rail && "md:hidden")}>
                {outOfCredits ? <span className="block pb-0.5">Reviews are paused.</span> : null}
                <span className="font-medium text-primary group-hover:underline">Top up →</span>
              </span>
            </Link>
            {DOCS_URL ? (
              <a
                href={DOCS_URL}
                target="_blank"
                rel="noreferrer"
                title={rail ? "Docs" : undefined}
                className={cn(itemCls, rail && "md:size-8 md:justify-center md:px-0")}
              >
                <BookOpen className="size-4 shrink-0" aria-hidden />
                <span className={label}>Docs</span>
              </a>
            ) : null}
          </div>
        </>
      )}

      <div
        className={cn(
          "flex h-11 shrink-0 items-center gap-2 border-t border-sidebar-border px-3",
          rail && "md:justify-center md:px-0",
          override && "md:hidden",
        )}
      >
        <Link
          href={`${base}/repos`}
          className={cn("flex min-w-0 flex-1 items-center gap-2 text-[13px] font-medium tracking-tight text-muted-foreground hover:text-foreground", rail && "md:hidden")}
        >
          <OwlMark className="size-4.5" />
          HootPR
        </Link>
        <button
          type="button"
          onClick={onToggleRail}
          aria-label={rail ? "Expand sidebar" : "Collapse sidebar"}
          title={rail ? "Expand sidebar" : "Collapse sidebar"}
          className="hidden size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none md:inline-flex"
        >
          {rail ? <PanelLeftOpen className="size-4" aria-hidden /> : <PanelLeftClose className="size-4" aria-hidden />}
        </button>
      </div>
    </div>
  );
}
