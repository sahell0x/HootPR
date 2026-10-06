"use client";
// Findings section (spec §11.2): every candidate the engine produced, grouped by what the judge did with it,
// mirroring where it ended up on the PR — inline comment, the walkthrough ("Additional comments" /
// "could not be posted inline"), or filtered out (dropped/merged, collapsed by default).
import {
  BookOpen,
  Bug,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleCheck,
  CircleDashed,
  CircleSlash,
  CircleX,
  Gauge,
  type LucideIcon,
  MessageSquareText,
  Paintbrush,
  ShieldAlert,
  TestTube2,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Tag } from "@/components/cr/review-chip";
import { CodeBlock } from "@/components/cr/review-code";
import { SEVERITY_LABEL, SeverityOutline } from "@/components/severity-badge";
import type { Finding, ReviewDetail, Severity } from "@/lib/api-types";
import { SEVERITY_ORDER, formatPct, lineSpan, severityRank } from "@/lib/format";
import { cn } from "@/lib/utils";

const VERDICT_CLS: Record<string, string> = {
  keep: "text-success",
  drop: "text-faint",
  merge: "text-chart-3",
};

const CATEGORY_ICON: [RegExp, LucideIcon][] = [
  [/secur|auth|secret|inject/i, ShieldAlert],
  [/bug|logic|correct|error/i, Bug],
  [/perf/i, Gauge],
  [/style|format|naming|nit/i, Paintbrush],
  [/test/i, TestTube2],
  [/doc/i, BookOpen],
  [/maint|refactor|complex|design/i, Wrench],
];

function findingIcon(f: Finding): LucideIcon {
  return (
    CATEGORY_ICON.find(([re]) => re.test(f.category))?.[1] ??
    (f.severity === "critical" || f.severity === "major" ? TriangleAlert : MessageSquareText)
  );
}

/** Where a finding's location chip links: the PR's changed-files view on GitHub / GitLab. */
function filesUrl(prUrl: string) {
  return /\/merge_requests\/\d+/.test(prUrl) ? `${prUrl.replace(/\/$/, "")}/diffs` : `${prUrl.replace(/\/$/, "")}/files`;
}

const EVIDENCE_CHIP =
  "inline-flex h-6 max-w-full min-w-0 items-center gap-1 rounded-sm border bg-background px-2 font-mono text-[0.6875rem] text-foreground/90";

function FindingItem({ f, prFiles }: { f: Finding; prFiles?: string }) {
  const [details, setDetails] = useState(true);
  const Icon = findingIcon(f);
  const evidence = (f.evidence ?? []).filter((e) => e && e !== f.path);
  // Evidence is either a location ("src/a.ts:41") or a short prose note; locations become chips.
  const extra = evidence.filter((e) => !/\s/.test(e));
  const notes = evidence.filter((e) => /\s/.test(e));
  const hasDetails = Boolean(f.suggestion || f.judge_verdict || f.category || f.confidence != null);
  const location = <span className="truncate" title={f.path}>{f.path} · {lineSpan(f.start_line, f.end_line)}</span>;
  return (
    <article className="flex min-w-0 flex-col gap-2.5 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <h4 className="flex min-w-0 flex-1 basis-64 items-start gap-2 text-[0.9375rem] leading-snug font-medium">
          <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 break-words">{f.title}</span>
        </h4>
        <SeverityOutline severity={f.severity} />
      </div>
      <p className="text-sm leading-relaxed break-words whitespace-pre-wrap text-muted-foreground">{f.body}</p>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-muted-foreground">Evidence</span>
        {prFiles ? (
          <a href={prFiles} target="_blank" rel="noreferrer" className={cn(EVIDENCE_CHIP, "transition-colors hover:border-foreground/30")}>
            {location}
            <ChevronRight className="size-3 shrink-0 text-muted-foreground" aria-hidden />
          </a>
        ) : (
          <span className={EVIDENCE_CHIP}>{location}</span>
        )}
        {extra.map((e) => (
          <span key={e} className={cn(EVIDENCE_CHIP, "text-muted-foreground")} title={e}>
            <span className="truncate">{e}</span>
          </span>
        ))}
      </div>
      {notes.length ? (
        <ul className="flex flex-col gap-1 border-l-2 pl-3 text-xs leading-relaxed text-muted-foreground">
          {notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      ) : null}
      {hasDetails ? (
        <button
          type="button"
          aria-expanded={details}
          onClick={() => setDetails((v) => !v)}
          className="inline-flex h-7 w-fit items-center gap-1.5 rounded-md border border-primary/70 px-2.5 text-xs text-foreground transition-colors hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {details ? <ChevronUp className="size-3.5 text-muted-foreground" aria-hidden /> : <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden />}
          {details ? "Hide details" : "Show details"}
        </button>
      ) : null}
      {hasDetails && details ? (
        <div className="flex flex-col gap-2.5">
          {f.suggestion ? <CodeBlock code={f.suggestion} label="Suggestion" accent /> : null}
          <div className="flex flex-wrap items-center gap-1.5">
            <Tag>{f.category}</Tag>
            {f.source !== "llm" ? <Tag className="font-mono">{f.source}</Tag> : null}
            <span className="ml-auto font-mono text-[0.6875rem] text-faint">confidence {formatPct(f.confidence)}</span>
          </div>
          {f.judge_verdict ? (
            <p className="text-xs leading-relaxed text-muted-foreground">
              <span className="eyebrow mr-1.5">Judge</span>
              <span className={cn("font-mono font-medium", VERDICT_CLS[f.judge_verdict])}>{f.judge_verdict}</span>
              {f.judge_reason ? ` — ${f.judge_reason}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function Group({ title, items, prFiles }: { title: string; items: Finding[]; prFiles?: string }) {
  const id = useId();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={id} className="flex flex-col border-t">
      <h3 id={id} className="flex items-center gap-2 bg-subtle px-4 py-2 text-[0.8125rem] font-medium text-muted-foreground sm:px-5">
        {title}
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm border bg-background px-1 font-mono text-[0.6875rem] text-faint">
          {items.length}
        </span>
      </h3>
      <div className="flex flex-col divide-y border-t">
        {items.map((f) => <FindingItem key={f.id} f={f} prFiles={prFiles} />)}
      </div>
    </section>
  );
}

function EmptyState({ review }: { review: ReviewDetail }) {
  const [Icon, msg, tone] =
    review.status === "completed"
      ? [CircleCheck, `No issues found — HootPR reviewed ${review.files_reviewed} of ${review.files_considered} files and had nothing to flag.`, "text-success"]
      : review.status === "skipped"
        ? [CircleSlash, `This review was skipped: ${review.skip_reason ?? "unknown reason"}.`, "text-muted-foreground"]
        : review.status === "queued" || review.status === "running"
          ? [CircleDashed, "The review is still running; findings appear when it finishes.", "text-chart-3"]
          : review.status === "failed"
            ? [CircleX, "The review failed before it produced findings.", "text-destructive"]
            : [CircleSlash, "This review produced no findings.", "text-muted-foreground"];
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <span className="mb-1 flex size-9 items-center justify-center rounded-md border bg-background">
        <Icon className={cn("size-4", tone)} aria-hidden />
      </span>
      <p className="max-w-md text-sm text-muted-foreground">{msg}</p>
    </div>
  );
}

const isFiltered = (f: Finding) => f.judge_verdict === "drop" || f.judge_verdict === "merge";

const SEG = "inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2.5 text-[0.8rem] font-medium transition-colors";

export function FindingsView({ review }: { review: ReviewDetail }) {
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [showFiltered, setShowFiltered] = useState(false);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of review.findings) c[f.severity] = (c[f.severity] ?? 0) + 1;
    return c;
  }, [review.findings]);
  const { posted, walkthrough, filtered } = useMemo(() => {
    const shown = review.findings
      .filter((f) => severity === "all" || f.severity === severity)
      .sort((a, b) => severityRank(a.severity) - severityRank(b.severity) || (b.confidence ?? 0) - (a.confidence ?? 0));
    return {
      posted: shown.filter((f) => f.posted),
      // Kept but not inline: chill-profile nitpicks, surplus over REVIEW_MAX_COMMENTS, 422 fallbacks.
      walkthrough: shown.filter((f) => !f.posted && !isFiltered(f)),
      filtered: shown.filter((f) => !f.posted && isFiltered(f)),
    };
  }, [review.findings, severity]);
  if (review.findings.length === 0) return <EmptyState review={review} />;
  const nothingShown = posted.length + walkthrough.length + filtered.length === 0;
  const prFiles = review.pr_url ? filesUrl(review.pr_url) : undefined;
  const seg = (active: boolean) =>
    cn(SEG, active ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground");
  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-5">
        <div
          className="inline-flex w-fit max-w-full flex-wrap gap-0.5 rounded-md border bg-background p-0.5"
          role="group"
          aria-label="Filter by severity"
        >
          <button type="button" className={seg(severity === "all")} aria-pressed={severity === "all"}
            onClick={() => setSeverity("all")}>
            All <span aria-hidden className="font-mono text-[0.6875rem] text-faint">{review.findings.length}</span>
          </button>
          {SEVERITY_ORDER.map((s) => (
            <button key={s} type="button" className={seg(severity === s)} aria-pressed={severity === s}
              onClick={() => setSeverity(s)}>
              {SEVERITY_LABEL[s]}
              <span aria-hidden className="font-mono text-[0.6875rem] text-faint">{counts[s] ?? 0}</span>
            </button>
          ))}
        </div>
      </div>
      {nothingShown ? (
        <p className="border-t px-4 py-6 text-sm text-muted-foreground sm:px-5">
          No {severity === "all" ? "" : `${severity} `}findings in this review.
        </p>
      ) : null}
      <Group title="Posted as inline comments" items={posted} prFiles={prFiles} />
      <Group title="In the walkthrough (additional or could not be posted inline)" items={walkthrough} prFiles={prFiles} />
      {filtered.length > 0 ? (
        <div className="flex flex-col border-t">
          <div className="px-4 py-3 sm:px-5">
            <button
              type="button"
              className="inline-flex w-fit items-center gap-1.5 rounded-md border border-dashed px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
              aria-expanded={showFiltered}
              onClick={() => setShowFiltered((v) => !v)}
            >
              <ChevronDown aria-hidden className={cn("size-4 transition-transform", showFiltered && "rotate-180")} />
              {showFiltered ? "Hide" : "Show"} {filtered.length} {filtered.length === 1 ? "finding" : "findings"} filtered
              out by the judge
            </button>
          </div>
          {showFiltered ? <Group title="Filtered out" items={filtered} prFiles={prFiles} /> : null}
        </div>
      ) : null}
    </div>
  );
}
