import { GitPullRequest } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { shortSha, timeAgo } from "@/lib/format";
import type { CsPull } from "@/lib/phase8-types";
import { cn } from "@/lib/utils";

export type CsTone = "primary" | "success" | "caution" | "destructive" | "muted";

const CHIP: Record<CsTone, string> = {
  primary: "border-primary/60 text-primary",
  success: "border-success/50 text-success",
  caution: "border-caution/60 text-caution",
  destructive: "border-destructive/60 text-destructive",
  muted: "border-border text-muted-foreground",
};
const DOT: Record<CsTone, string> = {
  primary: "bg-primary",
  success: "bg-success",
  caution: "bg-caution",
  destructive: "bg-destructive",
  muted: "bg-faint",
};
const RULE: Record<CsTone, string> = {
  primary: "border-primary/70",
  success: "border-success/60",
  caution: "border-caution/70",
  destructive: "border-destructive/70",
  muted: "border-border",
};

/** "● P0"-style chip: small outlined chip with a status dot. */
export function DotChip({ tone, children, className }: { tone: CsTone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-5 w-fit items-center gap-1.5 rounded-md border px-1.5 text-[11px] font-medium", CHIP[tone], className)}>
      <span aria-hidden className={cn("size-1.5 rounded-full", DOT[tone])} />
      {children}
    </span>
  );
}

/** Neutral tag chip ("Low security risk" style). */
export function TagChip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-5 items-center rounded-sm border border-border px-1.5 text-[11px] text-muted-foreground", className)}>
      {children}
    </span>
  );
}

export function reviewStatus(p: CsPull): { tone: CsTone; label: string } {
  if (p.last_reviewed_sha == null) return { tone: "primary", label: "Not reviewed" };
  if (p.last_reviewed_sha === p.head_sha) return { tone: "success", label: "Up to date" };
  return { tone: "caution", label: `Stale (${shortSha(p.last_reviewed_sha)})` };
}

/** Triage-style card for one pull request in the Change Stack list. */
export function CsPullCard({ p, href }: { p: CsPull; href: string }) {
  const s = reviewStatus(p);
  return (
    <Link
      href={href}
      className="group flex flex-col gap-2.5 rounded-lg border bg-card p-3.5 transition-colors hover:border-foreground/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-center justify-between gap-2">
        <DotChip tone={s.tone}>{s.label}</DotChip>
        <span className="font-mono text-[11px] text-faint">{timeAgo(p.updated_at)}</span>
      </div>
      <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
        {p.is_draft ? <span className="text-muted-foreground">Draft · </span> : null}
        {p.title}
      </p>
      <p className={cn("border-l-2 pl-2.5 text-xs leading-relaxed break-words text-muted-foreground", RULE[s.tone])}>
        @{p.author_username} wants to merge <code className="font-mono break-all text-foreground/85">{p.head_ref}</code> into{" "}
        <code className="font-mono text-foreground/85">{p.base_ref}</code>
      </p>
      <div className="flex flex-wrap gap-1.5">
        <TagChip className="capitalize">{p.state}</TagChip>
        {p.is_draft ? <TagChip>Draft</TagChip> : null}
        <TagChip>{p.provider === "gitlab" ? "GitLab" : "GitHub"}</TagChip>
        <TagChip className="font-mono">{shortSha(p.head_sha)}</TagChip>
      </div>
      <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-faint">
        <GitPullRequest className="size-3 shrink-0" aria-hidden />
        <span className="truncate">
          <span className="text-muted-foreground group-hover:text-foreground">{p.repo_full_name} #{p.number}</span> · @{p.author_username}
        </span>
        <span aria-hidden className="ml-auto grid size-5 shrink-0 place-items-center rounded-full bg-accent text-[9px] font-medium text-muted-foreground uppercase">
          {p.author_username.slice(0, 2)}
        </span>
      </div>
    </Link>
  );
}

/** Frame holding the triage columns side by side with a hairline between them. */
export function CsBoard({ children }: { children: ReactNode }) {
  return (
    <div className="grid overflow-hidden rounded-lg border bg-background max-lg:divide-y lg:grid-cols-2 lg:divide-x">{children}</div>
  );
}

/** "Now / Next" style column: header with title, caption and a mono count box. */
export function CsColumn({
  title,
  caption,
  count,
  children,
}: {
  title: string;
  caption: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-col">
      <header className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
        <div className="min-w-0">
          <h2 className="text-[13px] font-medium">{title}</h2>
          <p className="text-[11px] text-muted-foreground">{caption}</p>
        </div>
        <span className="inline-flex h-5 min-w-6 items-center justify-center rounded-sm border px-1 font-mono text-[11px] tabular-nums text-muted-foreground">{count}</span>
      </header>
      <div className="flex flex-col gap-3 px-4 pb-4">{children}</div>
    </section>
  );
}
