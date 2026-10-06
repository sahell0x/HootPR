import Link from "next/link";
import type { ReactNode } from "react";
import { Brand } from "@/components/brand";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Minimal full-page frame for errors and not-found pages (CodeRabbit-style): brand top-left,
 * a big mono code, one line of copy and the actions. Used outside the app shell.
 */
export function ShellErrorFrame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-1 flex-col bg-background", className)}>
      <header className="flex h-14 items-center border-b border-border px-4 sm:px-6">
        <Brand className="text-sm" />
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-16">{children}</main>
    </div>
  );
}

/** Centered code + title + description + actions. `code` is the big mono label ("404", "500"…). */
export function ShellErrorPanel({
  code,
  title,
  description,
  actions,
  role,
}: {
  code?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  role?: "alert";
}) {
  return (
    <div role={role} className="flex w-full max-w-md flex-col items-center gap-3 text-center">
      {code ? (
        <p aria-hidden className="font-mono text-[64px] leading-none font-medium tracking-tight text-foreground/90 sm:text-[88px]">
          {code}
        </p>
      ) : null}
      <h1 className="mt-2 text-xl font-medium tracking-tight text-balance">{title}</h1>
      {description ? <p className="text-sm text-pretty text-muted-foreground">{description}</p> : null}
      {actions ? <div className="mt-3 flex flex-wrap items-center justify-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function ShellErrorLink({ href, children, primary }: { href: string; children: ReactNode; primary?: boolean }) {
  return (
    <Link href={href} className={buttonVariants({ variant: primary ? "inverse" : "outline" })}>
      {children}
    </Link>
  );
}
