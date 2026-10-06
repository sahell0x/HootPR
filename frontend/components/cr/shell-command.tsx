"use client";
import { ArrowRightLeft, CornerDownLeft, Search, SearchX } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { NAV_ITEMS, ORG_SETTINGS, ORG_SETTINGS_ITEMS, type NavItem } from "./shell-nav";

type Entry = NavItem & { group: string; to: string };

/** ⌘K palette: jump to any page of the current organization. */
export function CommandPalette({
  orgSlug,
  open,
  onOpenChange,
}: {
  orgSlug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  const entries = useMemo<Entry[]>(
    () => [
      ...NAV_ITEMS.map((i) => ({ ...i, group: "Pages", to: `/o/${orgSlug}/${i.href}` })),
      ...ORG_SETTINGS_ITEMS.map((i) => ({ ...i, group: ORG_SETTINGS.label, to: `/o/${orgSlug}/${i.href}` })),
      { href: "", label: "Switch organization", icon: ArrowRightLeft, group: "Organization", to: "/orgs" },
    ],
    [orgSlug],
  );
  const q = query.trim().toLowerCase();
  const shown = q ? entries.filter((e) => `${e.label} ${e.group}`.toLowerCase().includes(q)) : entries;
  const active = Math.min(index, Math.max(shown.length - 1, 0));

  const go = (e: Entry | undefined) => {
    if (!e) return;
    onOpenChange(false);
    router.push(e.to);
  };

  const groups = [...new Set(shown.map((e) => e.group))];

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) {
          setQuery("");
          setIndex(0);
        }
      }}
    >
      <DialogContent
        showCloseButton={false}
        className="top-[15vh] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-lg"
      >
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">Type to filter pages, use arrow keys and Enter to open one.</DialogDescription>
        <div className="flex h-11 items-center gap-2 border-b border-border px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setIndex(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setIndex((i) => (shown.length ? (Math.min(i, shown.length - 1) + 1) % shown.length : 0));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setIndex((i) => (shown.length ? (Math.min(i, shown.length - 1) - 1 + shown.length) % shown.length : 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                go(shown[active]);
              }
            }}
            placeholder="Search pages…"
            aria-label="Search pages"
            role="combobox"
            aria-expanded
            aria-controls="shell-command-list"
            aria-activedescendant={shown[active] ? `cmd-${shown[active].to}` : undefined}
            className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="rounded-sm border border-border px-1.5 font-mono text-[11px] text-muted-foreground">Esc</kbd>
        </div>
        <div id="shell-command-list" role="listbox" aria-label="Pages" className="max-h-80 overflow-y-auto p-1.5">
          {shown.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-3 py-10 text-center">
              <SearchX className="size-5 text-faint" aria-hidden />
              <p className="max-w-full truncate text-sm text-muted-foreground">No results for “{query}”.</p>
            </div>
          ) : (
            groups.map((g) => (
              <div key={g} role="group" aria-label={g} className="pb-1">
                <div className="px-2 pt-1.5 pb-1 text-xs text-muted-foreground">{g}</div>
                {shown
                  .filter((e) => e.group === g)
                  .map((e) => {
                    const i = shown.indexOf(e);
                    const Icon = e.icon;
                    return (
                      <div
                        key={e.to}
                        id={`cmd-${e.to}`}
                        role="option"
                        aria-selected={i === active}
                        onMouseMove={() => setIndex(i)}
                        onClick={() => go(e)}
                        className={cn(
                          "flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2 text-sm text-muted-foreground",
                          i === active && "bg-accent text-foreground",
                        )}
                      >
                        <Icon className="size-4 shrink-0" aria-hidden />
                        <span className="flex-1 truncate">{e.label}</span>
                        {i === active ? <CornerDownLeft className="size-3.5" aria-hidden /> : null}
                      </div>
                    );
                  })}
              </div>
            ))
          )}
        </div>
        <div className="hidden h-9 items-center gap-4 border-t border-border bg-subtle px-3 text-xs text-muted-foreground sm:flex">
          <span className="flex items-center gap-1.5">
            <kbd className="rounded-sm border border-border px-1 font-mono text-[10px]">↑↓</kbd> Navigate
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="rounded-sm border border-border px-1 font-mono text-[10px]">↵</kbd> Open
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="rounded-sm border border-border px-1 font-mono text-[10px]">Esc</kbd> Close
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
