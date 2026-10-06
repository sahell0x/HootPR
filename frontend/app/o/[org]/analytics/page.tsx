"use client";
import { ChevronDown, Download, FolderGit2, History, ListOrdered, Users } from "lucide-react";
import { useParams } from "next/navigation";
import { type ReactNode, useState } from "react";
import { BarList, DailyActivityChart, DashboardSkeleton, EmptyState, InfoStrip, usePaged } from "@/components/cr/dash-ui";
import { MetricCard, MetricGrid, SectionTitle, Segmented, TablePagination } from "@/components/cr/kit";
import { PageHeader } from "@/components/cr/page-header";
import { fmtInt, formatDuration } from "@/components/phase8/ui";
import { QueryState } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ReviewStatus } from "@/lib/api-types";
import { formatCredits, formatPct, formatUsd, timeAgo } from "@/lib/format";
import { exportUrl, useMetrics, useUsage } from "@/lib/phase8-api";

const EXPORTS = [
  { kind: "reviews", format: "csv" },
  { kind: "findings", format: "csv" },
  { kind: "usage", format: "csv" },
  { kind: "reviews", format: "json" },
] as const;

function ExportMenu({ slug, days }: { slug: string; days: number }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline"><Download aria-hidden /> Export <ChevronDown aria-hidden className="text-muted-foreground" /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel className="eyebrow">Last {days} days</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {EXPORTS.map(({ kind, format }) => (
          <DropdownMenuItem key={`${kind}.${format}`} asChild>
            <a href={exportUrl(slug, kind, format, days)} download>
              <Download aria-hidden className="text-muted-foreground" />
              <span className="font-mono text-xs">{kind}.{format}</span>
            </a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const C = (n: 1 | 2 | 3 | 4 | 5) => `var(--chart-${n})`;
const BASE = "var(--faint)";

const asOf = () => new Date().toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function MetricsTab({ slug, days }: { slug: string; days: number }) {
  const q = useMetrics(slug, days);
  if (!q.data) return q.error ? <QueryState error={q.error} what="Analytics" /> : <DashboardSkeleton />;
  const m = q.data;
  const status = Object.fromEntries(m.reviews_by_status.map((c) => [c.key, c.count]));
  const blocked = m.daily.reduce((a, d) => a + d.blocked, 0);
  // LLM cost is internal: the API only returns it to platform owners.
  const showCost = m.per_repo.some((r) => r.cost_usd != null);
  const perPr = m.pull_requests ? (m.reviews_total / m.pull_requests).toFixed(1) : null;
  return <MetricsBody m={m} days={days} status={status} blocked={blocked} showCost={showCost} perPr={perPr} />;
}

function MetricsBody({ m, days, status, blocked, showCost, perPr }: {
  m: NonNullable<ReturnType<typeof useMetrics>["data"]>; days: number; status: Record<string, number>; blocked: number; showCost: boolean; perPr: string | null;
}) {
  const repos = usePaged(m.per_repo);
  const authors = usePaged(m.per_author);
  return (
    <div className="flex flex-col">
      <SectionTitle>Key Metrics</SectionTitle>
      <MetricGrid className="grid-cols-2 gap-3 sm:gap-4">
        <MetricCard title="Reviews" value={fmtInt(m.reviews_total)} caption={`${status.completed ?? 0} completed · past ${days} days`} />
        <MetricCard title="Pull requests" value={fmtInt(m.pull_requests)} caption={perPr ? `${perPr} reviews per PR` : "No pull requests yet"} />
        <MetricCard title="Findings posted" value={fmtInt(m.findings_total)} caption={`${m.findings_by_severity.find((f) => f.key === "critical")?.count ?? 0} critical`} />
        <MetricCard
          title="Acceptance rate"
          value={formatPct(m.acceptance.rate)}
          caption={`${m.acceptance.accepted} accepted · ${m.acceptance.dismissed} dismissed · ${m.acceptance.open} open`}
        />
        <MetricCard
          title="Time to first review"
          value={formatDuration(m.time_to_first_review.median_s)}
          caption={`median · p90 ${formatDuration(m.time_to_first_review.p90_s)}`}
        />
        <MetricCard title="Blocked" value={fmtInt(blocked)} caption="rate limited or out of credits" />
      </MetricGrid>

      <SectionTitle className="mt-10">Daily Activity</SectionTitle>
      <InfoStrip
        title={`Median time to first review: ${formatDuration(m.time_to_first_review.median_s)}`}
        caption={<>{fmtInt(m.reviews_total)} {m.reviews_total === 1 ? "review" : "reviews"} in the past {days} days <span className="text-faint">— as of {asOf()}</span></>}
      />
      <DailyActivityChart
        className="mt-5"
        yLabel="Reviews (per day)"
        points={m.daily.map((d) => ({ day: d.day, values: [d.reviews - d.completed - d.blocked, d.blocked, d.completed] }))}
        series={[
          { label: "Other", color: BASE },
          { label: "Blocked", color: C(5) },
          { label: "Completed", color: C(2) },
        ]}
      />

      <SectionTitle className="mt-10">Findings</SectionTitle>
      <div className="grid gap-4 lg:grid-cols-2">
        <FrameCard title="By severity"><BarList items={m.findings_by_severity} color={C(5)} /></FrameCard>
        <FrameCard title="By category"><BarList items={m.findings_by_category} color={C(4)} /></FrameCard>
      </div>

      <SectionTitle className="mt-10">By repository</SectionTitle>
      {m.per_repo.length === 0 ? <EmptyState icon={FolderGit2} className="py-8">No repository activity in this period.</EmptyState> : (<>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Repository</TableHead><TableHead>Reviews</TableHead><TableHead>Completed</TableHead>
            <TableHead>Findings</TableHead><TableHead>Acceptance</TableHead>{showCost ? <TableHead>LLM cost</TableHead> : null}
          </TableRow></TableHeader>
          <TableBody>
            {repos.rows.map((r) => (
              <TableRow key={r.repo_id}>
                <TableCell className="max-w-[26rem] truncate font-medium" title={r.repo_full_name}>{r.repo_full_name}</TableCell>
                <TableCell className="tabular-nums">{r.reviews}</TableCell><TableCell className="tabular-nums">{r.completed}</TableCell>
                <TableCell className="tabular-nums">{r.findings}</TableCell>
                <TableCell className="tabular-nums">{formatPct(r.acceptance_rate)}</TableCell>{showCost ? <TableCell className="tabular-nums">{formatUsd(r.cost_usd)}</TableCell> : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {repos.paged ? <TablePagination {...repos} /> : null}
      </>)}

      <SectionTitle className="mt-10">By author</SectionTitle>
      {m.per_author.length === 0 ? <EmptyState icon={Users} className="py-8">No pull request authors in this period.</EmptyState> : (<>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Author</TableHead><TableHead>Pull requests</TableHead><TableHead>Reviews</TableHead>
            <TableHead>Findings</TableHead><TableHead>Critical + major</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {authors.rows.map((a) => (
              <TableRow key={a.author}>
                <TableCell className="max-w-[20rem] truncate font-medium text-primary" title={`@${a.author}`}>@{a.author}</TableCell><TableCell className="tabular-nums">{a.pull_requests}</TableCell>
                <TableCell className="tabular-nums">{a.reviews}</TableCell>
                <TableCell className="tabular-nums">{a.findings}</TableCell><TableCell className="tabular-nums">{a.critical_major}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {authors.paged ? <TablePagination {...authors} /> : null}
      </>)}
    </div>
  );
}

/** Plain bordered frame with a 15px title (MetricCard's outer frame, for chart/list content). */
function FrameCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="mb-4 text-[0.9375rem] font-medium">{title}</p>
      {children}
    </div>
  );
}

function UsageTab({ slug, days }: { slug: string; days: number }) {
  const q = useUsage(slug, days);
  if (!q.data) return q.error ? <QueryState error={q.error} what="Usage" /> : <DashboardSkeleton cards={4} />;
  const u = q.data;
  // Tokens / LLM cost are internal: the API only returns them to platform owners.
  const internal = u.input_tokens != null;
  return <UsageBody u={u} days={days} internal={internal} />;
}

function UsageBody({ u, days, internal }: { u: NonNullable<ReturnType<typeof useUsage>["data"]>; days: number; internal: boolean }) {
  const reviews = usePaged(u.reviews);
  const ledger = usePaged(u.ledger);
  return (
    <div className="flex flex-col">
      <SectionTitle>Key Metrics</SectionTitle>
      <MetricGrid className="grid-cols-2 gap-3 sm:gap-4">
        <MetricCard title="Review events" value={fmtInt(u.review_events)} caption={`${u.completed} completed · ${u.failed} failed · ${u.skipped} skipped`} />
        <MetricCard title="Blocked" value={fmtInt(u.rate_limited + u.no_credits)} caption={`${u.rate_limited} rate limited · ${u.no_credits} out of credits`} />
        <MetricCard title="Credits spent" value={formatCredits(u.credits_spent)} caption={`${formatCredits(u.credits_refunded)} refunded · past ${days} days`} />
        <MetricCard title="Chat replies" value={fmtInt(u.chat_replies)} caption={`${formatCredits(u.chat_credits)} credits`} />
        {internal ? (
          <>
            <MetricCard title="Tokens" value={<span className="block truncate max-sm:text-2xl">{fmtInt((u.input_tokens ?? 0) + (u.output_tokens ?? 0))}</span>} caption={u.avg_tokens_per_review == null ? "—" : `${fmtInt(Math.round(u.avg_tokens_per_review))} per review`} />
            <MetricCard title="LLM cost" value={<span className="block truncate max-sm:text-2xl" title={formatUsd(u.cost_usd)}>{formatUsd(u.cost_usd)}</span>} caption={`${formatUsd(u.avg_cost_per_review)} per review (internal)`} />
          </>
        ) : null}
      </MetricGrid>

      <SectionTitle className="mt-10">Daily Activity</SectionTitle>
      <InfoStrip
        title={`Credits balance: ${formatCredits(u.balance)}`}
        caption={<>{fmtInt(u.review_events)} review {u.review_events === 1 ? "event" : "events"} in the past {days} days <span className="text-faint">— as of {asOf()}</span></>}
      />
      <DailyActivityChart
        className="mt-5"
        yLabel="Review events (per day)"
        points={u.daily.map((d) => ({ day: d.day, values: [d.completed, d.blocked] }))}
        series={[{ label: "Completed", color: C(2) }, { label: "Blocked", color: C(5) }]}
      />

      <SectionTitle className="mt-10">{internal ? "Credits, tokens and cost per review" : "Credits per review"}</SectionTitle>
      {u.reviews.length === 0 ? <EmptyState icon={ListOrdered} className="py-8">No reviews in this period.</EmptyState> : (<>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Status</TableHead><TableHead>Pull request</TableHead><TableHead>Credits</TableHead>
            {internal ? <><TableHead>Input / cached / output</TableHead><TableHead>LLM cost</TableHead></> : null}
            <TableHead>When</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {reviews.rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell><StatusBadge status={r.status as ReviewStatus} /></TableCell>
                <TableCell className="max-w-[22rem] truncate font-medium" title={`${r.repo_full_name} #${r.pr_number}`}>{r.repo_full_name} <span className="text-muted-foreground">#{r.pr_number}</span></TableCell>
                <TableCell className="tabular-nums">{formatCredits(r.credits_charged)}</TableCell>
                {internal ? (
                  <>
                    <TableCell className="tabular-nums">{fmtInt(r.input_tokens ?? 0)} / {fmtInt(r.cached_tokens ?? 0)} / {fmtInt(r.output_tokens ?? 0)}</TableCell>
                    <TableCell className="tabular-nums">{formatUsd(r.cost_usd)}</TableCell>
                  </>
                ) : null}
                <TableCell className="whitespace-nowrap text-muted-foreground">{timeAgo(r.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {reviews.paged ? <TablePagination {...reviews} /> : null}
      </>)}

      <SectionTitle className="mt-10">Credits ledger</SectionTitle>
      {u.ledger.length === 0 ? <EmptyState icon={History} className="py-8">No credit movements in this period.</EmptyState> : (<>
        <Table>
          <TableHeader><TableRow>
            <TableHead>When</TableHead><TableHead>Reason</TableHead><TableHead>Change</TableHead><TableHead>Balance</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {ledger.rows.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="text-muted-foreground">{timeAgo(e.created_at)}</TableCell>
                <TableCell className="capitalize">{e.reason.replaceAll("_", " ")}</TableCell>
                <TableCell className={Number(e.delta) < 0 ? "text-destructive tabular-nums" : "text-success tabular-nums"}>{Number(e.delta) > 0 ? "+" : ""}{formatCredits(e.delta)}</TableCell>
                <TableCell className="tabular-nums">{formatCredits(e.balance_after)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {ledger.paged ? <TablePagination {...ledger} /> : null}
      </>)}
    </div>
  );
}

const PERIODS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
] as const;
type Section = "metrics" | "usage";

export default function AnalyticsPage() {
  const { org: slug } = useParams<{ org: string }>();
  const [days, setDays] = useState(30);
  const [section, setSection] = useState<Section>("metrics");
  return (
    <div className="flex flex-col">
      <PageHeader
        title="Dashboard"
        description="Review activity, findings and credit usage across your repositories."
        actions={<ExportMenu slug={slug} days={days} />}
      />
      <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
        <Segmented<Section>
          value={section}
          onChange={setSection}
          options={[{ value: "metrics", label: "Metrics" }, { value: "usage", label: "Review usage" }]}
        />
        <Segmented
          label="Period"
          className="[&_button]:px-2 [&_button]:whitespace-nowrap sm:[&_button]:px-3"
          value={String(days)}
          onChange={(v) => setDays(Number(v))}
          options={PERIODS}
        />
      </div>
      {section === "metrics" ? <MetricsTab slug={slug} days={days} /> : <UsageTab slug={slug} days={days} />}
    </div>
  );
}
