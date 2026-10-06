"use client";
import { useQueryClient } from "@tanstack/react-query";
import { Bug, ChevronDown, ChevronUp, FolderGit2, Loader2, Radar, Scale, ShieldAlert, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { EmptyState } from "@/components/cr/dash-ui";
import { MetricCard, MetricGrid } from "@/components/cr/kit";
import { PageContainer, PageHeader } from "@/components/cr/page-header";
import { QueryState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import { formatCredits, shortSha, timeAgo } from "@/lib/format";
import {
  type RepoSecurity,
  type RiskLevel,
  type ScanKind,
  type ScanSummary,
  securityApi,
  securityKeys,
  useSecurityOverview,
  useSecurityScan,
} from "@/lib/security-api";
import { cn } from "@/lib/utils";

const RISK_CHIP: Record<RiskLevel, string> = {
  critical: "border-destructive/60 text-destructive bg-destructive/5",
  high: "border-destructive/50 text-destructive",
  medium: "border-caution/50 text-caution",
  low: "border-success/50 text-success",
};
const RISK_WORD: Record<RiskLevel, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

/** Outlined risk chip: "Overall: High risk", "High severity". */
function RiskChip({ risk, prefix, suffix = "risk" }: { risk: RiskLevel; prefix?: string; suffix?: string }) {
  return (
    <span className={cn("inline-flex h-5 shrink-0 items-center rounded-sm border px-1.5 font-sans text-xs font-medium whitespace-nowrap", RISK_CHIP[risk])}>
      {prefix ? `${prefix}: ` : ""}{RISK_WORD[risk]} {suffix}
    </span>
  );
}

function ReviewSection({ icon: Icon, title, chip, children }: {
  icon: React.ComponentType<{ className?: string }>; title: React.ReactNode; chip?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-center gap-2">
        <Icon aria-hidden className="size-4 text-muted-foreground" />
        <h4 className="text-[0.9375rem] font-medium">{title}</h4>
        {chip}
      </div>
      {children}
    </section>
  );
}

function Evidence({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="mr-1 text-muted-foreground">Evidence</span>
      {items.map((a) => (
        <code key={a} title={a} className="inline-block h-6 max-w-full truncate rounded-sm border bg-subtle px-2 align-middle font-mono text-xs leading-[22px]">{a}</code>
      ))}
    </div>
  );
}

const STATUS_TEXT: Record<ScanSummary["status"], string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  no_credits: "Out of credits",
};

function Stat({ label, value, warn }: { label: string; value: number | undefined; warn?: boolean }) {
  return (
    <div className="rounded-md border bg-subtle px-3 py-2">
      <div className="eyebrow truncate">{label}</div>
      <div className={cn("mt-0.5 text-lg font-medium tabular-nums", warn && (value ?? 0) > 0 && "text-caution")}>
        {value ?? "—"}
      </div>
    </div>
  );
}

function ScanDetailView({ slug, scanId }: { slug: string; scanId: string }) {
  const q = useSecurityScan(slug, scanId);
  if (!q.data) return q.error ? <QueryState error={q.error} what="This scan" className="h-32" /> : <Skeleton className="h-48" />;
  const { surface, report } = q.data;
  return (
    <Tabs defaultValue={report ? "report" : "entries"} className="mt-2">
      <TabsList variant="line" className="h-9 w-full justify-start gap-4 overflow-x-auto rounded-none border-b p-0">
        {report ? <TabsTrigger value="report" className="flex-none px-0 pb-2">Report</TabsTrigger> : null}
        <TabsTrigger value="entries" className="flex-none px-0 pb-2">Entry points ({surface?.entry_points.length ?? 0})</TabsTrigger>
        <TabsTrigger value="outbound" className="flex-none px-0 pb-2">Outbound ({surface?.outbound.length ?? 0})</TabsTrigger>
        <TabsTrigger value="secrets" className="flex-none px-0 pb-2">Secrets ({surface?.secrets.length ?? 0})</TabsTrigger>
        <TabsTrigger value="iac" className="flex-none px-0 pb-2">Infrastructure ({surface?.iac.length ?? 0})</TabsTrigger>
      </TabsList>
      {report ? (
        <TabsContent value="report" className="mt-4">
          <div className="divide-y rounded-md border bg-card">
            <ReviewSection icon={Scale} title="Assessment" chip={<RiskChip risk={report.overall_risk} prefix="Overall" />}>
              <p className="text-sm leading-relaxed whitespace-pre-line text-foreground/90">{report.summary}</p>
            </ReviewSection>
            {report.risks.map((r, i) => (
              <ReviewSection key={i} icon={r.severity === "critical" || r.severity === "high" ? TriangleAlert : Bug}
                title={r.title}
                chip={<><span className="eyebrow">{r.category}</span><span className="ml-auto"><RiskChip risk={r.severity} suffix="severity" /></span></>}>
                <p className="text-sm leading-relaxed whitespace-pre-line text-foreground/90">{r.description}</p>
                <Evidence items={r.affected} />
                <p className="text-sm"><span className="font-medium">Fix: </span><span className="text-muted-foreground">{r.recommendation}</span></p>
              </ReviewSection>
            ))}
            {report.strengths.length ? (
              <ReviewSection icon={ShieldCheck} title="Strengths">
                <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-foreground/90">{report.strengths.map((x) => <li key={x}>{x}</li>)}</ul>
              </ReviewSection>
            ) : null}
          </div>
        </TabsContent>
      ) : null}
      <TabsContent value="entries">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Entry point</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Auth</TableHead>
              <TableHead>Location</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(surface?.entry_points ?? []).slice(0, 500).map((e, i) => (
              <TableRow key={i}>
                <TableCell><code>{e.name}</code></TableCell>
                <TableCell className="text-xs">{e.framework} {e.kind}</TableCell>
                <TableCell className="text-xs">
                  {e.auth ? (
                    <span className="inline-flex items-center gap-1"><ShieldCheck className="size-3" aria-hidden />{e.auth_evidence ?? "yes"}</span>
                  ) : e.kind === "http" ? (
                    <span className="inline-flex items-center gap-1 text-caution"><ShieldAlert className="size-3" aria-hidden />none detected</span>
                  ) : "—"}
                </TableCell>
                <TableCell className="font-mono text-xs">{e.path}:{e.line}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TabsContent>
      <TabsContent value="outbound">
        <ul className="flex flex-col divide-y rounded-md border bg-card font-mono text-xs [&>li]:px-4 [&>li]:py-2">
          {(surface?.outbound ?? []).map((x, i) => (
            <li key={i}>{x.callee} — {x.symbol || "module"} ({x.path}:{x.line})</li>
          ))}
        </ul>
      </TabsContent>
      <TabsContent value="secrets">
        <ul className="flex flex-col divide-y rounded-md border bg-card font-mono text-xs [&>li]:px-4 [&>li]:py-2">
          {(surface?.secrets ?? []).map((x, i) => (
            <li key={i}>{x.name} [{x.source === "env" ? "env var" : "committed env file"}] ({x.path}:{x.line})</li>
          ))}
        </ul>
      </TabsContent>
      <TabsContent value="iac">
        <ul className="flex flex-col divide-y rounded-md border bg-card text-xs [&>li]:px-4 [&>li]:py-2">
          {(surface?.iac ?? []).map((x, i) => (
            <li key={i}>
              <Badge variant="outline" className="mr-2">{x.kind}</Badge>
              {x.detail} <span className="font-mono text-muted-foreground">({x.path}:{x.line})</span>
            </li>
          ))}
        </ul>
      </TabsContent>
    </Tabs>
  );
}

function RepoCard({ slug, repo, costLabel, canReview }: {
  slug: string; repo: RepoSecurity; costLabel: string; canReview: boolean;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<ScanKind | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const running = (k: ScanKind) => repo.active.some((a) => a.kind === k);
  const stats = repo.latest_surface?.stats;
  const review = repo.latest_review;
  const shown = review?.status === "completed" ? review : repo.latest_surface;

  const start = async (kind: ScanKind) => {
    setBusy(kind);
    try {
      await securityApi.start(slug, repo.repo_id, kind);
      toast.success(kind === "security_review" ? "Security review started" : "Attack surface scan started");
      await qc.invalidateQueries({ queryKey: securityKeys.overview(slug) });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not start the scan.");
    } finally {
      setBusy(null);
    }
  };

  const risk = review?.status === "completed" ? review.overall_risk : null;
  const reviewNote = review && review.status !== "completed" && !running("security_review");
  return (
    <article className="overflow-hidden rounded-md border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-4 last:border-b-0 sm:px-5">
        <div className="min-w-0 flex-1 basis-72">
          <h3 className="flex min-w-0 items-center gap-2 font-mono text-sm font-medium">
            <FolderGit2 aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate" title={repo.full_name}>{repo.full_name}</span>
            {risk ? <RiskChip risk={risk} prefix="Overall" /> : null}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {repo.latest_surface
              ? `Attack surface of ${repo.latest_surface.branch}@${shortSha(repo.latest_surface.commit_sha)}, mapped ${timeAgo(repo.latest_surface.created_at)}`
              : "No attack surface map yet."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={busy !== null || running("surface_map")} onClick={() => void start("surface_map")}>
            {running("surface_map") ? <Loader2 className="animate-spin" aria-hidden /> : <Radar aria-hidden />}
            {running("surface_map") ? "Mapping…" : "Map attack surface"}
          </Button>
          {canReview ? (
            <Button variant="outline" size="sm" disabled={busy !== null || running("security_review")} onClick={() => void start("security_review")}>
              {running("security_review") ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden className="text-primary" />}
              {running("security_review") ? "Reviewing…" : `Run security review (${costLabel})`}
            </Button>
          ) : null}
        </div>
      </div>
      {stats || reviewNote || shown ? <div className="flex flex-col gap-4 px-4 py-4 sm:px-5">
        {stats ? (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label="HTTP endpoints" value={stats.http_endpoints} />
            <Stat label="Without auth" value={stats.unauthenticated_endpoints} warn />
            <Stat label="Outbound calls" value={stats.outbound_calls} />
            <Stat label="Secrets refs" value={stats.secrets} warn />
            <Stat label="IaC exposure" value={stats.iac_findings} warn />
          </div>
        ) : null}
        {review && reviewNote ? (
          <p className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
            review.status === "failed" ? "border-destructive/30 bg-destructive/5 text-destructive"
              : review.status === "no_credits" ? "border-caution/30 bg-caution/5 text-caution" : "text-muted-foreground")}>
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            <span>Last security review: {STATUS_TEXT[review.status]}{review.summary ? ` — ${review.summary}` : ""}</span>
          </p>
        ) : null}
        {shown ? (
          <div>
            <Button variant="outline" size="sm" onClick={() => setOpen(open ? null : shown.id)} aria-expanded={open !== null}>
              {open ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
              {open ? "Hide details" : shown.kind === "security_review" ? "View report" : "View map"}
            </Button>
          </div>
        ) : null}
        {open ? <ScanDetailView slug={slug} scanId={open} /> : null}
      </div> : null}
    </article>
  );
}

export default function SecurityPage() {
  const { org: slug } = useParams<{ org: string }>();
  const q = useSecurityOverview(slug);
  if (!q.data) {
    if (q.error) return <QueryState error={q.error} what="Security" backHref="/orgs" />;
    return (
      <PageContainer className="flex flex-col gap-6">
        <div className="flex flex-col gap-2"><Skeleton className="h-7 w-32" /><Skeleton className="h-4 w-[36rem] max-w-full" /><Skeleton className="h-4 w-[30rem] max-w-full" /></div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
        <Skeleton className="h-6 w-32" />
        {[0, 1].map((i) => <Skeleton key={i} className="h-40" />)}
      </PageContainer>
    );
  }
  const { repos, credits_security_review: cost, can_run_review: canReview } = q.data;
  const costLabel = `up to ${formatCredits(cost)} credits`;
  const sum = (k: "http_endpoints" | "unauthenticated_endpoints" | "secrets" | "iac_findings") =>
    repos.reduce((n, r) => n + (r.latest_surface?.stats?.[k] ?? 0), 0);
  const mapped = repos.filter((r) => r.latest_surface).length;
  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        className="mb-0"
        title="Security"
        description={
          <span className="block max-w-3xl">
            Attack surface maps inventory each repository&apos;s entry points, auth checks, outbound calls,
            secrets usage and infrastructure exposure (free). A security architecture review adds an AI report
            with prioritized risks ({costLabel}). You can also comment <code className="rounded-sm bg-muted px-1 font-mono text-xs">@hootpr security review</code> on a
            pull request. Pull request walkthroughs show the blast radius and attack surface changes.
          </span>
        }
      />
      {repos.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="Nothing to scan">
          No repositories yet. Install HootPR on a repository first.
        </EmptyState>
      ) : (
        <>
          <MetricGrid className="grid-cols-2 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard title="Repositories mapped" value={`${mapped} / ${repos.length}`} caption="Have an attack surface map" />
            <MetricCard title="HTTP endpoints" value={sum("http_endpoints")} caption="Across mapped repositories" />
            <MetricCard title="Without auth" value={sum("unauthenticated_endpoints")} caption="No auth check detected" />
            <MetricCard title="Exposure" value={sum("secrets") + sum("iac_findings")} caption="Secrets refs + IaC findings" />
          </MetricGrid>
          <h2 className="mt-2 text-lg font-medium tracking-tight">Repositories</h2>
          {repos.map((r) => <RepoCard key={r.repo_id} slug={slug} repo={r} costLabel={costLabel} canReview={canReview} />)}
        </>
      )}
    </PageContainer>
  );
}
