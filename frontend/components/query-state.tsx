"use client";
import { CircleAlert, SearchX } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * What a page shows while its data is missing: a skeleton while loading, a sign-in redirect on
 * 401, a not-found state on 404/422 (e.g. a malformed id), otherwise the error message. Never an
 * endless skeleton.
 */
export function QueryState({
  error,
  what,
  backHref,
  className = "h-96",
}: {
  error: Error | null | undefined;
  /** Noun for the not-found message, e.g. "This review". */
  what: string;
  backHref?: string;
  className?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const unauthenticated = error instanceof ApiError && error.status === 401;

  useEffect(() => {
    if (unauthenticated) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthenticated, pathname, router]);

  if (!error) return <Skeleton className={className} aria-busy="true" />;
  if (unauthenticated) return null;
  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-6 py-14 text-center">
        <SearchX className="size-6 text-muted-foreground" aria-hidden />
        <h1 className="mt-1 text-base font-medium tracking-tight">{what} was not found.</h1>
        <p className="text-sm text-muted-foreground">The link may be wrong, or it was removed.</p>
        {backHref ? (
          <Link className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-2")} href={backHref}>
            Go back
          </Link>
        ) : null}
      </div>
    );
  }
  return (
    <Alert variant="destructive" role="alert" className="max-w-lg">
      <CircleAlert aria-hidden />
      <AlertDescription>{error.message || "Something went wrong. Please try again."}</AlertDescription>
    </Alert>
  );
}
