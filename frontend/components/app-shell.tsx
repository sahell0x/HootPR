"use client";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { CommandPalette } from "@/components/cr/shell-command";
import { breadcrumbs } from "@/components/cr/shell-nav";
import { ShellSidebar } from "@/components/cr/shell-sidebar";
import { useShellSlots } from "@/components/cr/shell-slots";
import { ShellTopbar } from "@/components/cr/shell-topbar";
import { api, ApiError } from "@/lib/api";
import type { Me, Org } from "@/lib/api-types";
import { clearAuthStorage } from "@/lib/auth-storage";
import { formatCredits } from "@/lib/format";
import { qk } from "@/lib/queries";
import { cn } from "@/lib/utils";

const RAIL_KEY = "hootpr:sidebar-collapsed";

async function signOut() {
  try {
    await api.logout();
  } catch (e) {
    // An expired session is already signed out; anything else is worth telling the user.
    if (!(e instanceof ApiError && e.status === 401)) {
      toast.error("Could not sign out. Try again.");
      return;
    }
  } finally {
    clearAuthStorage();
  }
  window.location.href = "/";
}

/**
 * CodeRabbit-style app frame: 232px sidebar (collapsible to a 56px icon rail on desktop, a drawer on
 * mobile) + a 48px top bar with breadcrumb, search (⌘K), notifications, help and the account menu.
 * Pages can take over the sidebar / breadcrumb title / top-bar actions through `components/cr/shell-slots`.
 */
export function AppShell({ org, me, children }: { org: Org; me?: Me; children: ReactNode }) {
  const pathname = usePathname();
  // Repo pages are addressed by id; resolve it to owner/name for the breadcrumb (shares the repos list cache).
  const onRepoPage = /\/repos\/[^/]+/.test(pathname);
  const repos = useQuery({ queryKey: qk.repos(org.slug), queryFn: () => api.repos(org.slug), enabled: onRepoPage });
  const repoNames = useMemo(
    () => Object.fromEntries((repos.data?.repos ?? []).map((r) => [r.id, r.full_name])),
    [repos.data],
  );
  const slots = useShellSlots();
  const credits = formatCredits(org.credits_balance);
  const outOfCredits = !(Number(org.credits_balance) > 0);
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState(false);
  const rail = collapsed && !slots.sidebar;

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(RAIL_KEY) === "1");
    } catch {
      /* storage unavailable: start expanded */
    }
  }, []);

  const toggleRail = useCallback(() => {
    setCollapsed((v) => {
      try {
        localStorage.setItem(RAIL_KEY, v ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !v;
    });
  }, []);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setDrawer(false), [pathname]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearch((v) => !v);
      } else if (e.key === "Escape") setDrawer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex min-h-0 flex-1">
      {drawer ? (
        <div aria-hidden className="fixed inset-0 z-40 bg-black/50 md:hidden" onClick={() => setDrawer(false)} />
      ) : null}
      <aside
        aria-label="Sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-[272px] max-w-[85vw] shrink-0 border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-transform duration-200",
          "md:static md:z-auto md:max-w-none md:translate-x-0 md:transition-none",
          drawer ? "translate-x-0" : "-translate-x-full max-md:invisible",
          rail ? "md:w-14" : "md:w-[232px]",
        )}
      >
        <div className="h-dvh md:sticky md:top-0 md:h-[calc(100dvh-var(--banner-h,0px))]">
          <ShellSidebar
            org={org}
            pathname={pathname}
            credits={credits}
            outOfCredits={outOfCredits}
            override={slots.sidebar}
            rail={rail}
            onToggleRail={toggleRail}
          />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <ShellTopbar
          crumbs={breadcrumbs(pathname, org.slug, org.name, repoNames)}
          title={slots.title}
          actions={slots.actions}
          me={me}
          drawerOpen={drawer}
          onToggleDrawer={() => setDrawer((v) => !v)}
          onToggleCollapse={toggleRail}
          onSearch={() => setSearch(true)}
          onSignOut={() => void signOut()}
        />
        <main className="min-w-0 flex-1 bg-background p-6 lg:p-8">{children}</main>
      </div>

      <CommandPalette orgSlug={org.slug} open={search} onOpenChange={setSearch} />
    </div>
  );
}
