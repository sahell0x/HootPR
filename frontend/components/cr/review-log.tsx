"use client";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, ChevronDown, ChevronRight, CirclePlus, ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ComponentProps } from "react";
import { StatusOutcome } from "@/components/status-badge";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ReviewStatus, ReviewSummary } from "@/lib/api-types";
import { STATUS_LABEL, formatCredits, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

export const TRIGGER_LABEL: Record<string, string> = {
  auto: "Initial review",
  incremental: "Incremental review",
  command_review: "Review command",
  command_full: "Full review command",
  manual: "Manual review",
};
export const triggerLabel = (t: string) => TRIGGER_LABEL[t] ?? t.replaceAll("_", " ");

/** "Sep 30, 10:35 AM" */
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Dashed-outline toolbar button (CodeRabbit's "Sort" / "⊕ Outcome"). */
export function DashedButton({ className, ...props }: ComponentProps<"button">) {
  return (
    <button
      type="button"
      {...props}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-2 rounded-md border border-dashed bg-transparent px-3 text-sm font-medium text-foreground transition-colors outline-none hover:bg-accent focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 [&_svg]:size-4 [&_svg]:text-muted-foreground",
        className,
      )}
    />
  );
}

export function SortButton({ dir, onToggle }: { dir: "desc" | "asc"; onToggle: () => void }) {
  const Icon = dir === "desc" ? ArrowDownWideNarrow : ArrowUpNarrowWide;
  return (
    <DashedButton onClick={onToggle} aria-label={`Sort: ${dir === "desc" ? "newest" : "oldest"} first`} title="Toggle newest / oldest first">
      <Icon aria-hidden /> Sort
      <span className="font-normal text-muted-foreground">{dir === "desc" ? "Newest" : "Oldest"}</span>
    </DashedButton>
  );
}

const OUTCOMES = Object.keys(STATUS_LABEL) as ReviewStatus[];

export function OutcomeFilter({
  value,
  onChange,
  counts,
}: {
  value: ReviewStatus[];
  onChange: (v: ReviewStatus[]) => void;
  counts: Partial<Record<ReviewStatus, number>>;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <DashedButton aria-label="Filter by outcome">
          <CirclePlus aria-hidden /> Outcome
          {value.length ? (
            <>
              <span aria-hidden className="h-4 w-px bg-border" />
              <span className="rounded-sm bg-accent px-1.5 text-xs font-normal">
                {value.length > 2 ? `${value.length} selected` : value.map((s) => STATUS_LABEL[s]).join(", ")}
              </span>
            </>
          ) : null}
        </DashedButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-52">
        {OUTCOMES.map((s) => (
          <DropdownMenuCheckboxItem
            key={s}
            checked={value.includes(s)}
            onSelect={(e) => e.preventDefault()}
            onCheckedChange={(on) => onChange(on ? [...value, s] : value.filter((v) => v !== s))}
          >
            <StatusOutcome status={s} />
            <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">{counts[s] ?? 0}</span>
          </DropdownMenuCheckboxItem>
        ))}
        {value.length ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onChange([])} className="justify-center">
              <X aria-hidden /> Clear filter
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function PrLink({ r, className }: { r: ReviewSummary; className?: string }) {
  return (
    <a
      href={r.pr_url}
      target="_blank"
      rel="noreferrer"
      aria-label={`${r.repo_full_name}#${r.pr_number} (opens the pull request)`}
      className={cn("inline-flex text-primary hover:text-primary/80", className)}
    >
      <ExternalLink className="size-4" aria-hidden />
    </a>
  );
}

/** One pull request in the "Pull requests" view: chevron row + nested table of its review events. */
export function PrGroup({
  slug,
  reviews,
  open,
  onToggle,
  internal,
}: {
  slug: string;
  /** This PR's reviews, in display order. */
  reviews: ReviewSummary[];
  open: boolean;
  onToggle: () => void;
  internal: boolean;
}) {
  const router = useRouter();
  const head = reviews[0]!;
  const name = `${head.repo_full_name} #${head.pr_number}`;
  // Review numbers count up chronologically inside the PR, whatever the display order.
  const chrono = [...reviews].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const num = new Map(chrono.map((r, i) => [r.id, i + 1]));
  const findings = reviews.reduce((a, r) => a + r.findings_posted, 0);
  const incremental = reviews.filter((r) => r.trigger === "incremental").length;
  const blocked = reviews.filter((r) => r.status === "rate_limited" || r.status === "no_credits").length;
  const summary = [
    plural(reviews.length, "review event"),
    incremental ? `${incremental} incremental` : null,
    plural(findings, "finding"),
    blocked ? `${blocked} blocked` : null,
  ].filter(Boolean).join(" · ");
  return (
    <div className="border-b">
      <div className="flex items-center gap-2 py-3 pr-1">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} reviews for ${name}`}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", !open && "-rotate-90")} aria-hidden />
          <span className="flex min-w-0 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
            <span className="truncate font-medium" title={head.pr_title}>{name}</span>
            <span className="truncate text-sm text-muted-foreground">{summary}</span>
          </span>
        </button>
        <PrLink r={head} className="p-1" />
      </div>
      {open ? (
        <div className="mb-4 ml-0 sm:ml-7">
          <Table className="min-w-[40rem]">
            <TableHeader><TableRow>
              <TableHead>Time</TableHead><TableHead>Review</TableHead><TableHead>Event</TableHead><TableHead>Outcome</TableHead>
              <TableHead>Findings</TableHead><TableHead>Credits</TableHead>
              {internal ? <><TableHead>Tokens</TableHead><TableHead>LLM cost</TableHead></> : null}
              <TableHead className="w-10"><span className="sr-only">Open</span></TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {reviews.map((r) => {
                const href = `/o/${slug}/reviews/${r.id}`;
                return (
                  <TableRow
                    key={r.id}
                    className="cursor-pointer"
                    onClick={(e) => {
                      if ((e.target as HTMLElement).closest("a,button")) return;
                      router.push(href);
                    }}
                  >
                    <TableCell className="whitespace-nowrap">{fmtTime(r.created_at)}</TableCell>
                    <TableCell className="tabular-nums">
                      <Link href={href} className="hover:underline">#{num.get(r.id)}</Link>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{triggerLabel(r.trigger)}</TableCell>
                    <TableCell><StatusOutcome status={r.status} title={r.skip_reason ?? undefined} /></TableCell>
                    <TableCell className={cn("tabular-nums", r.findings_posted > 0 && "text-caution")}>{r.findings_posted}</TableCell>
                    <TableCell className="tabular-nums">{formatCredits(r.credits_charged)}</TableCell>
                    {internal ? (
                      <>
                        <TableCell className="text-muted-foreground tabular-nums">{r.input_tokens ?? "—"} / {r.output_tokens ?? "—"}</TableCell>
                        <TableCell className="text-muted-foreground tabular-nums">{formatUsd(r.cost_usd)}</TableCell>
                      </>
                    ) : null}
                    <TableCell className="w-10 pl-0 text-right">
                      <Link href={href} aria-label="Details" className="inline-flex align-middle text-muted-foreground hover:text-foreground">
                        <ChevronRight className="size-4" aria-hidden />
                      </Link>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}

/** Flat "Timeline" table: every review event, one row each. */
export function TimelineTable({ slug, reviews, internal }: { slug: string; reviews: ReviewSummary[]; internal: boolean }) {
  const router = useRouter();
  return (
    <Table>
      <TableHeader><TableRow>
        <TableHead>Pull request</TableHead><TableHead>Outcome</TableHead>
        <TableHead className="hidden md:table-cell">Event</TableHead>
        <TableHead>Findings</TableHead><TableHead>Credits</TableHead>
        {internal ? <><TableHead>Tokens</TableHead><TableHead>LLM cost</TableHead></> : null}
        <TableHead>Time</TableHead><TableHead className="w-10"><span className="sr-only">Open</span></TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {reviews.map((r) => {
          const href = `/o/${slug}/reviews/${r.id}`;
          return (
            <TableRow
              key={r.id}
              className="cursor-pointer"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest("a,button")) return;
                router.push(href);
              }}
            >
              <TableCell className="max-w-56 min-w-48 whitespace-normal sm:max-w-[28rem] sm:min-w-56">
                <span className="flex min-w-0 items-center gap-1.5">
                  <Link href={href} className="truncate font-medium text-primary hover:underline" title={`${r.repo_full_name} #${r.pr_number}`}>
                    {r.repo_full_name} #{r.pr_number}
                  </Link>
                  <PrLink r={r} />
                </span>
                <span className="mt-0.5 line-clamp-1 text-sm break-all text-muted-foreground" title={r.pr_title}>{r.pr_title}</span>
              </TableCell>
              <TableCell><StatusOutcome status={r.status} title={r.skip_reason ?? undefined} /></TableCell>
              <TableCell className="hidden whitespace-nowrap text-muted-foreground md:table-cell">{triggerLabel(r.trigger)}</TableCell>
              <TableCell className={cn("tabular-nums", r.findings_posted > 0 && "text-caution")}>{r.findings_posted}</TableCell>
              <TableCell className="tabular-nums">{formatCredits(r.credits_charged)}</TableCell>
              {internal ? (
                <>
                  <TableCell className="text-muted-foreground tabular-nums">{r.input_tokens ?? "—"} / {r.output_tokens ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground tabular-nums">{formatUsd(r.cost_usd)}</TableCell>
                </>
              ) : null}
              <TableCell className="whitespace-nowrap text-muted-foreground" title={new Date(r.created_at).toLocaleString()}>
                {fmtTime(r.created_at)}
              </TableCell>
              <TableCell className="w-10 pl-0 text-right">
                <Link href={href} aria-label="Details" className="inline-flex align-middle text-muted-foreground hover:text-foreground">
                  <ChevronRight className="size-4" aria-hidden />
                </Link>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
