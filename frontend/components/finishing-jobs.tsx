"use client";
import { useQuery } from "@tanstack/react-query";
import { Bug, FileText, FlaskConical, GitMerge, type LucideIcon, Recycle, Siren, Sparkles, Wand2, Wrench } from "lucide-react";
import { Chip, type ChipTone } from "@/components/cr/review-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { FinishingJob, FinishingJobList, FinishingKind } from "@/lib/finishing-types";
import { creditsLabel, shortSha, timeAgo } from "@/lib/format";

const KIND: Record<FinishingKind, { label: string; icon: LucideIcon }> = {
  docstrings: { label: "Docstrings", icon: FileText },
  unit_tests: { label: "Unit tests", icon: FlaskConical },
  autofix: { label: "Autofix", icon: Wrench },
  simplify: { label: "Simplify", icon: Recycle },
  fix_ci: { label: "Fix CI", icon: Bug },
  ci_analysis: { label: "CI analysis", icon: Siren },
  merge_conflict: { label: "Merge conflict", icon: GitMerge },
  custom: { label: "Recipe", icon: Wand2 },
};

const VERIFICATION: Record<FinishingJob["verification"], { label: string; tone: ChipTone } | null> = {
  verified: { label: "tests passed", tone: "success" },
  failed: { label: "tests failing", tone: "danger" },
  couldnt_verify: { label: "couldn't verify", tone: "caution" },
  not_run: null,
};

const STATUS_TONE: Record<string, ChipTone> = {
  queued: "neutral", running: "info", completed: "success", failed: "danger", cancelled: "faint", skipped: "faint",
};

function Result({ job }: { job: FinishingJob }) {
  if (job.delivery === "stacked_pr" && job.result_pr_number !== null) {
    return job.result_url ? (
      <a className="hover:underline" href={job.result_url} target="_blank" rel="noreferrer">
        stacked PR #{job.result_pr_number}
      </a>
    ) : (
      <span>stacked PR #{job.result_pr_number}</span>
    );
  }
  if (job.result_sha) {
    const label = <code className="font-mono text-xs">{shortSha(job.result_sha)}</code>;
    return job.result_url ? (
      <a className="hover:underline" href={job.result_url} target="_blank" rel="noreferrer">
        commit {label}
      </a>
    ) : (
      <span>commit {label}</span>
    );
  }
  if (job.delivery === "comment" && job.status === "completed") return <span>comment</span>;
  if (job.error) return <span className="text-destructive" title={job.error}>{job.error}</span>;
  return <span className="text-muted-foreground">{job.status === "queued" || job.status === "running" ? "in progress" : "no result"}</span>;
}

/** Finishing-touch jobs of one review's pull request (docstrings, unit tests, autofix, …). */
export function FinishingJobs({ slug, reviewId }: { slug: string; reviewId: string }) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["orgs", slug, "finishing-jobs", { reviewId }],
    queryFn: () =>
      apiFetch<FinishingJobList>(
        `/api/orgs/${encodeURIComponent(slug)}/finishing-jobs?review_id=${encodeURIComponent(reviewId)}`,
      ),
    refetchInterval: (q) =>
      q.state.data?.jobs?.some((j) => j.status === "queued" || j.status === "running") ? 5000 : false,
  });
  if (isLoading)
    return (
      <div className="flex flex-col divide-y" aria-busy="true" aria-label="Loading finishing touches">
        {[0, 1].map((i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
            <Skeleton className="size-4" />
            <Skeleton className="h-4 w-40" />
            <Skeleton className="ml-auto h-5 w-20" />
          </div>
        ))}
      </div>
    );
  if (error) return <p className="px-4 py-4 text-sm text-destructive sm:px-5">Could not load finishing touches.</p>;
  const jobs = data?.jobs ?? [];
  if (jobs.length === 0)
    return (
      <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
        <Sparkles className="size-5 text-muted-foreground" aria-hidden />
        <p className="font-medium">No finishing touches yet</p>
        <p className="max-w-xl text-sm leading-relaxed text-muted-foreground [&_code]:rounded-sm [&_code]:border [&_code]:bg-surface [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs [&_code]:text-foreground">
        No finishing touches yet. Comment <code>@hootpr generate docstrings</code>,{" "}
        <code>generate unit tests</code>, <code>autofix</code>, <code>simplify</code>, <code>fix ci</code>,{" "}
        <code>resolve merge conflict</code> or <code>run &lt;recipe&gt;</code> on the pull request.
        </p>
      </div>
    );
  return (
    <ul aria-label="Finishing touches" className="flex flex-col divide-y">
      {jobs.map((j) => {
        const K = KIND[j.kind] ?? { label: j.kind, icon: Sparkles };
        const v = VERIFICATION[j.verification];
        return (
          <li key={j.id} className="flex flex-col gap-2 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5">
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border bg-background">
                <K.icon className="size-3.5 text-muted-foreground" aria-hidden />
              </span>
              <div className="flex min-w-0 flex-col gap-0.5">
                <p className="flex min-w-0 items-baseline gap-1.5 text-sm font-medium">
                  <span className="shrink-0">{K.label}</span>
                  {j.recipe_name ? <span className="truncate font-mono text-xs font-normal text-muted-foreground">{j.recipe_name}</span> : null}
                </p>
                <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                  <span className="max-w-full truncate [&_a]:text-foreground"><Result job={j} /></span>
                  {j.files_changed ? <span>· {j.files_changed} files</span> : null}
                  <span className="text-faint">·</span>
                  <span className="whitespace-nowrap">{j.requested_by ? `@${j.requested_by}` : "webhook"} · {timeAgo(j.created_at)}</span>
                </p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2 pl-10 sm:pl-0">
              {v ? <Chip tone={v.tone}>{v.label}</Chip> : null}
              <Chip tone={STATUS_TONE[j.status] ?? "neutral"} pulse={j.status === "running" || j.status === "queued"} className="capitalize">
                {j.status.replace("_", " ")}
              </Chip>
              <span className="min-w-20 text-right text-xs whitespace-nowrap text-muted-foreground tabular-nums" title="Credits charged">
                {creditsLabel(j.credits_charged)}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
