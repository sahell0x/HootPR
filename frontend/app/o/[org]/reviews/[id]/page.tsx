"use client";
import { useQueryClient } from "@tanstack/react-query";
import { CircleX, ExternalLink, ListChecks, Loader2, ScrollText } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { CollapsibleSection, SectionTabs } from "@/components/cr/cs-section";
import { CreditReceiptCard } from "@/components/credit-receipt";
import { Tag } from "@/components/cr/review-chip";
import { TopbarTitle } from "@/components/cr/shell-slots";
import { FindingsView } from "@/components/findings-view";
import { FinishingJobs } from "@/components/finishing-jobs";
import { QueryState } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { TraceView } from "@/components/trace-view";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import type { ReviewDetail } from "@/lib/api-types";
import { STATUS_LABEL, formatCredits, formatMs, shortSha, timeAgo } from "@/lib/format";
import { qk, useReview } from "@/lib/queries";
import { cn } from "@/lib/utils";

type SectionId = "summary" | "credits" | "findings" | "finishing" | "trace";

const isFiltered = (v: string | null | undefined) => v === "drop" || v === "merge";

function outcome(r: ReviewDetail, duration: number | null) {
  if (r.status === "completed") return `Completed in ${formatMs(duration)}`;
  if (r.status === "skipped") return `Skipped${r.skip_reason ? `: ${r.skip_reason}` : ""}`;
  if (r.status === "queued" || r.status === "running") return "Still in progress";
  return STATUS_LABEL[r.status] ?? r.status;
}

function Summary({ review, duration }: { review: ReviewDetail; duration: number | null }) {
  const posted = review.findings.filter((f) => f.posted).length;
  const filtered = review.findings.filter((f) => !f.posted && isFiltered(f.judge_verdict)).length;
  const walkthrough = review.findings.length - posted - filtered;
  const tasks = review.trace.tasks;
  return (
    <div className="flex flex-col divide-y">
      <div className="flex flex-col gap-3 p-4 sm:p-5">
        <h3 className="flex items-center gap-2 text-[0.9375rem] font-medium">
          <ScrollText className="size-4 text-muted-foreground" aria-hidden /> Review summary
        </h3>
        <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm leading-relaxed text-muted-foreground marker:text-faint">
          <li><span className="font-medium text-foreground">Outcome</span> — {outcome(review, duration)}</li>
          <li><span className="font-medium text-foreground">Coverage</span> — {review.files_reviewed} of {review.files_considered} files reviewed</li>
          <li>
            <span className="font-medium text-foreground">Findings</span> — {review.findings.length}{" "}
            {review.findings.length === 1 ? "candidate" : "candidates"}: {posted} posted inline, {walkthrough} in the walkthrough,{" "}
            {filtered} dropped or merged by the judge
          </li>
        </ul>
      </div>
      {tasks.length ? (
        <div className="flex flex-col gap-3 p-4 sm:p-5">
          <h3 className="flex items-center gap-2 text-[0.9375rem] font-medium">
            <ListChecks className="size-4 text-muted-foreground" aria-hidden /> Walkthrough
          </h3>
          <ol className="flex flex-col gap-3">
            {tasks.map((t) => (
              <li key={t.id} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2">
                <span className="pt-px font-mono text-xs text-faint">{String(t.ordinal + 1).padStart(2, "0")}</span>
                <div className="flex min-w-0 flex-col gap-1">
                  <p className="text-sm font-medium">{t.title}</p>
                  {t.summary ? <p className="text-sm leading-relaxed text-muted-foreground">{t.summary}</p> : null}
                  {t.files.length ? (
                    <div className="flex flex-wrap gap-1">
                      {t.files.map((f) => <Tag key={f} className="max-w-full truncate font-mono">{f}</Tag>)}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

/** Live strip while the review is queued / running: spinner, last stage, indeterminate bar. */
function Progress({ review }: { review: ReviewDetail }) {
  const stages = review.trace.stages;
  const last = stages.at(-1);
  const queued = review.status === "queued";
  return (
    <div role="status" className="overflow-hidden rounded-lg border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 sm:px-5">
        <Loader2 className="size-4 shrink-0 animate-spin text-chart-3" aria-hidden />
        <p className="text-sm font-medium">{queued ? "Waiting for a review worker…" : "Review in progress"}</p>
        <p className="text-sm text-muted-foreground">
          {queued
            ? "It starts as soon as a worker is free."
            : last
              ? <>{stages.length} {stages.length === 1 ? "stage" : "stages"} done · last: <span className="font-mono text-xs text-foreground">{last.name}</span></>
              : "Preparing the checkout…"}
        </p>
        <span className="ml-auto text-xs text-faint">Updates automatically</span>
      </div>
      <div className="h-0.5 w-full overflow-hidden bg-subtle">
        <div className="h-full w-1/3 animate-[hoot-progress_1.6s_ease-in-out_infinite] bg-chart-3/70" />
      </div>
      <style>{`@keyframes hoot-progress{0%{transform:translateX(-100%)}100%{transform:translateX(300%)}}`}</style>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading">
      <div className="flex flex-col gap-3 pt-1">
        <Skeleton className="h-8 w-2/3 max-w-xl" />
        <Skeleton className="h-5 w-64 max-w-full" />
      </div>
      <Skeleton className="h-9 w-full max-w-md" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-baseline gap-3 px-5 py-2.5">
      <dt className="text-[0.8125rem] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm break-words">{children}</dd>
    </div>
  );
}

function MetaPanel({ review, duration }: { review: ReviewDetail; duration: number | null }) {
  const posted = review.findings.filter((f) => f.posted).length;
  const when = (iso: string) => <span title={new Date(iso).toLocaleString()}>{timeAgo(iso)}</span>;
  return (
    <div className="flex flex-col">
      <div className="flex h-12 items-center gap-3 border-b px-5 text-xs text-muted-foreground">
        <span className="h-px flex-1 bg-border" aria-hidden />
        <span className="whitespace-nowrap">Review · {new Date(review.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</span>
        <span className="h-px flex-1 bg-border" aria-hidden />
      </div>
      <dl className="flex flex-col py-2">
        <MetaRow label="Status"><StatusBadge status={review.status} /></MetaRow>
        <MetaRow label="Pull request">
          <a className="inline-flex max-w-full items-center gap-1 font-mono text-[0.8125rem] text-primary hover:underline" href={review.pr_url} target="_blank" rel="noreferrer">
            <span className="truncate">{review.repo_full_name}#{review.pr_number}</span>
            <ExternalLink className="size-3 shrink-0" aria-hidden />
          </a>
        </MetaRow>
        <MetaRow label="Head commit">
          <code className="rounded-sm border bg-subtle px-1 font-mono text-xs">{shortSha(review.head_sha)}</code>
        </MetaRow>
        <MetaRow label="Trigger"><span className="font-mono text-[0.8125rem]">{review.trigger}</span></MetaRow>
      </dl>
      <dl className="flex flex-col border-t py-2">
        <MetaRow label="Credits">
          <span className="tabular-nums">{formatCredits(review.credits_charged)}</span>{" "}
          <span className="text-xs text-muted-foreground">charged for this review</span>
        </MetaRow>
        <MetaRow label="Files">
          <span className="tabular-nums">{review.files_reviewed}</span>{" "}
          <span className="text-xs text-muted-foreground">of {review.files_considered} reviewed</span>
        </MetaRow>
        <MetaRow label="Findings">
          <span className="tabular-nums">{review.findings.length}</span>{" "}
          <span className="text-xs text-muted-foreground">{posted} posted inline</span>
        </MetaRow>
        <MetaRow label="Duration">
          <span className="tabular-nums">{formatMs(duration)}</span>{" "}
          <span className="text-xs text-muted-foreground">{review.finished_at ? "wall clock" : "in progress"}</span>
        </MetaRow>
      </dl>
      <dl className="flex flex-col border-t py-2">
        <MetaRow label="Started">{when(review.created_at)}</MetaRow>
        {review.finished_at ? <MetaRow label="Finished">{when(review.finished_at)}</MetaRow> : null}
        {review.skip_reason ? <MetaRow label="Skipped"><span className="text-caution">{review.skip_reason}</span></MetaRow> : null}
      </dl>
      <div className="border-t p-5">
        <a href={review.pr_url} target="_blank" rel="noreferrer" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}>
          <ExternalLink aria-hidden /> Open pull request
        </a>
      </div>
    </div>
  );
}

export default function ReviewDetailPage() {
  const { org: slug, id } = useParams<{ org: string; id: string }>();
  const { data, error } = useReview(slug, id);
  const [open, setOpen] = useState<Record<SectionId, boolean>>({ summary: true, credits: true, findings: true, finishing: true, trace: false });
  const [active, setActive] = useState<SectionId>("summary");
  const qc = useQueryClient();
  const live = data?.status === "queued" || data?.status === "running";
  // Poll while the review is still going so the page shows its progress without a reload.
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => void qc.invalidateQueries({ queryKey: qk.review(slug, id) }), 5000);
    return () => clearInterval(t);
  }, [live, qc, slug, id]);
  if (!data) return error ? <QueryState error={error} what="This review" backHref={`/o/${slug}/reviews`} /> : <DetailSkeleton />;
  const duration = data.finished_at ? new Date(data.finished_at).getTime() - new Date(data.created_at).getTime() : null;
  const toggle = (s: SectionId) => (v: boolean) => setOpen((o) => ({ ...o, [s]: v }));
  const jump = (s: SectionId) => {
    setActive(s);
    setOpen((o) => ({ ...o, [s]: true }));
    requestAnimationFrame(() => document.getElementById(s)?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  };
  const receipt = data.receipt ?? null;
  const tabs: { id: SectionId; label: string; count?: number }[] = [
    { id: "summary", label: "Summary" },
    ...(receipt ? [{ id: "credits" as const, label: "Credits" }] : []),
    { id: "findings", label: "Findings", count: data.findings.length },
    { id: "finishing", label: "Finishing touches" },
    { id: "trace", label: "Trace" },
  ];
  return (
    <div className="xl:-my-8 xl:-mr-8 xl:grid xl:min-h-dvh xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="flex min-w-0 flex-col gap-6 xl:py-8 xl:pr-8">
        <header className="flex flex-col gap-3 pt-1">
          <TopbarTitle>{data.pr_title}</TopbarTitle>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 flex-col gap-2">
              <h1 className="text-2xl font-medium tracking-tight break-words">
                {data.pr_title} <span className="font-normal text-faint">#{data.pr_number}</span>
              </h1>
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
                <StatusBadge status={data.status} />
                <span className="font-mono text-xs text-foreground">{data.repo_full_name}</span>
                <span className="text-faint">·</span>
                <span>started {timeAgo(data.created_at)}</span>
              </p>
            </div>
            <a
              href={data.pr_url}
              target="_blank"
              rel="noreferrer"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }), "xl:hidden")}
            >
              <ExternalLink aria-hidden /> Open pull request
            </a>
          </div>
        </header>
        <SectionTabs label="Review sections" items={tabs} active={active} onSelect={jump} className="-mt-1" />
        {live ? <Progress review={data} /> : null}
        {data.error ? (
          <Alert variant="destructive" className="border-destructive/30 bg-destructive/5">
            <CircleX aria-hidden />
            <AlertTitle>{data.status === "failed" ? "Review failed" : "Review error"}</AlertTitle>
            <AlertDescription className="break-words">{data.error}</AlertDescription>
          </Alert>
        ) : null}
        <CollapsibleSection id="summary" title="Summary" open={open.summary} onOpenChange={toggle("summary")}>
          <Summary review={data} duration={duration} />
        </CollapsibleSection>
        {receipt ? (
          <CollapsibleSection id="credits" title="Credits" open={open.credits} onOpenChange={toggle("credits")}>
            <CreditReceiptCard receipt={receipt} />
          </CollapsibleSection>
        ) : null}
        <CollapsibleSection id="findings" title="Findings" count={data.findings.length} open={open.findings} onOpenChange={toggle("findings")}>
          <FindingsView review={data} />
        </CollapsibleSection>
        <CollapsibleSection id="finishing" title="Finishing touches" open={open.finishing} onOpenChange={toggle("finishing")}>
          <FinishingJobs slug={slug} reviewId={id} />
        </CollapsibleSection>
        <CollapsibleSection id="trace" title="Trace" open={open.trace} onOpenChange={toggle("trace")} bodyClassName="p-4 sm:p-5">
          <TraceView review={data} slug={slug} />
        </CollapsibleSection>
      </div>
      <aside aria-label="Review details" className="mt-8 rounded-lg border bg-card xl:mt-0 xl:rounded-none xl:border-0 xl:border-l xl:bg-transparent">
        <div className="xl:sticky xl:top-0">
          <MetaPanel review={data} duration={duration} />
        </div>
      </aside>
    </div>
  );
}
