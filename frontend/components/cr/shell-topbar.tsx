"use client";
import { Bell, BookOpen, ChevronDown, CircleHelp, LogOut, PanelLeft, Search, User } from "lucide-react";
import Link from "next/link";
import { Fragment, type ReactNode } from "react";
import { Popover as PopoverPrimitive } from "radix-ui";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Me } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { DOCS_URL, ISSUES_URL, type Crumb } from "./shell-nav";

const iconBtn = "text-muted-foreground hover:text-foreground";

export function ShellTopbar({
  crumbs,
  title,
  actions,
  me,
  drawerOpen,
  onToggleDrawer,
  onToggleCollapse,
  onSearch,
  onSignOut,
}: {
  crumbs: Crumb[];
  title: ReactNode | null;
  actions: ReactNode | null;
  me?: Me;
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  onToggleCollapse: () => void;
  onSearch: () => void;
  onSignOut: () => void;
}) {
  const initials = me?.display_name.slice(0, 2).toUpperCase();
  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background px-3 md:px-4">
      <Button
        variant="ghost"
        size="icon-sm"
        className={cn(iconBtn, "md:hidden")}
        aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
        aria-expanded={drawerOpen}
        onClick={onToggleDrawer}
      >
        <PanelLeft aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        className={cn(iconBtn, "hidden md:inline-flex")}
        aria-label="Toggle sidebar"
        onClick={onToggleCollapse}
      >
        <PanelLeft aria-hidden />
      </Button>

      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex min-w-0 items-center gap-1.5 text-sm">
          {crumbs.map((c, i) => {
            const last = i === crumbs.length - 1;
            return (
              <Fragment key={i}>
                {i > 0 ? (
                  <li aria-hidden className="hidden shrink-0 text-faint md:block">
                    /
                  </li>
                ) : null}
                <li
                  className={cn(
                    "min-w-0 truncate",
                    last ? "shrink-0 max-w-full md:max-w-[40%]" : "hidden max-w-[16rem] shrink md:block",
                  )}
                  title={last ? undefined : c.label}
                >
                  {last ? (
                    <span aria-current="page" className="block truncate font-medium text-foreground">
                      {title ?? c.label}
                    </span>
                  ) : c.href ? (
                    <Link href={c.href} className="text-muted-foreground transition-colors hover:text-foreground">
                      {c.label}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">{c.label}</span>
                  )}
                </li>
              </Fragment>
            );
          })}
        </ol>
      </nav>

      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}

      <button
        type="button"
        onClick={onSearch}
        className="hidden h-8 w-52 items-center gap-2 rounded-md border border-border bg-subtle px-2.5 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none lg:flex"
      >
        <Search className="size-3.5" aria-hidden />
        <span className="flex-1 text-left">Search</span>
        <kbd className="font-mono text-[11px] text-faint">⌘K</kbd>
      </button>
      <div className="flex shrink-0 items-center gap-0.5">
        <Button variant="ghost" size="icon-sm" className={cn(iconBtn, "lg:hidden")} aria-label="Search" onClick={onSearch}>
          <Search aria-hidden />
        </Button>
        <PopoverPrimitive.Root>
          <PopoverPrimitive.Trigger asChild>
            <Button variant="ghost" size="icon-sm" className={iconBtn} aria-label="Notifications">
              <Bell aria-hidden />
            </Button>
          </PopoverPrimitive.Trigger>
          <PopoverPrimitive.Portal>
            <PopoverPrimitive.Content
              align="end"
              sideOffset={6}
              className="z-50 w-72 rounded-md border border-border bg-popover text-popover-foreground shadow-md outline-none"
            >
              <div className="border-b border-border px-3 py-2 text-sm font-medium">Notifications</div>
              <div className="flex flex-col items-center gap-1.5 px-3 py-8 text-center">
                <Bell className="size-5 text-faint" aria-hidden />
                <p className="text-sm text-muted-foreground">No notifications</p>
              </div>
            </PopoverPrimitive.Content>
          </PopoverPrimitive.Portal>
        </PopoverPrimitive.Root>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" className={cn(iconBtn, "hidden sm:inline-flex")} aria-label="Help">
              <CircleHelp aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="text-xs text-muted-foreground">Help</DropdownMenuLabel>
            <DropdownMenuItem onSelect={onSearch}>
              <Search aria-hidden /> Search pages
              <DropdownMenuShortcut>⌘K</DropdownMenuShortcut>
            </DropdownMenuItem>
            {DOCS_URL ? (
              <DropdownMenuItem asChild>
                <a href={DOCS_URL} target="_blank" rel="noreferrer">
                  <BookOpen aria-hidden /> Documentation
                </a>
              </DropdownMenuItem>
            ) : null}
            {ISSUES_URL ? (
              <DropdownMenuItem asChild>
                <a href={ISSUES_URL} target="_blank" rel="noreferrer">
                  <CircleHelp aria-hidden /> Report an issue
                </a>
              </DropdownMenuItem>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
        {DOCS_URL ? (
          <Button variant="ghost" size="icon-sm" className={cn(iconBtn, "hidden sm:inline-flex")} asChild>
            <a href={DOCS_URL} target="_blank" rel="noreferrer" aria-label="Documentation">
              <BookOpen aria-hidden />
            </a>
          </Button>
        ) : null}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="Account menu"
              className="ml-1 flex items-center gap-1 rounded-md p-1 text-muted-foreground transition-colors hover:bg-subtle hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <Avatar className="size-6">
                <AvatarImage src={me?.avatar_url ?? undefined} alt="" />
                <AvatarFallback className="text-[0.6rem]">{initials ?? <User className="size-3.5" aria-hidden />}</AvatarFallback>
              </Avatar>
              <ChevronDown className="size-3.5" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            {me ? (
              <>
                <div className="px-2 py-1.5">
                  <p className="truncate text-sm font-medium">{me.display_name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {me.email ?? (me.identities[0] ? `@${me.identities[0].username}` : "Signed in")}
                  </p>
                </div>
                <DropdownMenuSeparator />
              </>
            ) : null}
            <DropdownMenuItem onSelect={onSignOut}>
              <LogOut aria-hidden /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
