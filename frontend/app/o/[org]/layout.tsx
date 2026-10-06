"use client";
import { RotateCw } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { AppShell } from "@/components/app-shell";
import { ShellErrorFrame, ShellErrorPanel } from "@/components/cr/shell-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useMe, useOrg } from "@/lib/queries";
import { useOrgSlug } from "@/lib/use-org-slug";

export default function OrgLayout({ children }: { children: ReactNode }) {
  const slug = useOrgSlug();
  const router = useRouter();
  const pathname = usePathname();
  const me = useMe();
  const org = useOrg(slug);
  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (unauthenticated) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthenticated, pathname, router]);

  if (unauthenticated) return null;
  if (org.error instanceof ApiError && (org.error.status === 404 || org.error.status === 403)) {
    return (
      <ShellErrorFrame>
        <ShellErrorPanel
          code={String(org.error.status)}
          title="Organization not found or you are not a member."
          description="Check the address, or pick one of your organizations."
          actions={
            <Link className={buttonVariants({ variant: "inverse" })} href="/orgs">
              Choose an organization
            </Link>
          }
        />
      </ShellErrorFrame>
    );
  }
  if (org.error) {
    return (
      <ShellErrorFrame>
        <ShellErrorPanel
          role="alert"
          code={org.error instanceof ApiError && org.error.status >= 500 ? String(org.error.status) : undefined}
          title="Could not load this organization."
          description={org.error.message || "Something went wrong. Please try again."}
          actions={
            <>
              <Button variant="inverse" onClick={() => void org.refetch()} disabled={org.isFetching}>
                <RotateCw aria-hidden className={org.isFetching ? "animate-spin" : undefined} /> Try again
              </Button>
              <Link className={buttonVariants({ variant: "outline" })} href="/orgs">
                Switch organization
              </Link>
            </>
          }
        />
      </ShellErrorFrame>
    );
  }
  if (!org.data) {
    return (
      <div className="flex min-h-[calc(100dvh-var(--banner-h,0px))] flex-1" aria-busy="true">
        <div className="hidden w-[232px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex">
          <div className="flex h-12 items-center gap-2 border-b border-sidebar-border px-3">
            <Skeleton className="size-4 rounded-sm" />
            <Skeleton className="h-4 w-28" />
          </div>
          <div className="flex flex-1 flex-col gap-1.5 p-2">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-7 w-full" />
            ))}
          </div>
          <div className="p-2">
            <Skeleton className="h-14 w-full" />
          </div>
          <div className="flex h-11 items-center gap-2 border-t border-sidebar-border px-3">
            <Skeleton className="size-4.5 rounded-sm" />
            <Skeleton className="h-3.5 w-16" />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-12 items-center gap-3 border-b border-border px-4">
            <Skeleton className="size-6" />
            <Skeleton className="h-4 w-48" />
          </div>
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6 lg:p-8">
            <Skeleton className="h-10 w-72" />
            <Skeleton className="h-80 w-full" />
          </div>
        </div>
      </div>
    );
  }
  return (
    <AppShell org={org.data} me={me.data}>
      {children}
    </AppShell>
  );
}
