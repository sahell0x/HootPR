"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CircleCheck, FileText, Loader2, Pencil, Play, PlusCircle, Sparkles, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { toastError } from "@/components/phase8/errors";
import { EmptyState } from "@/components/cr/dash-ui";
import { Segmented, SectionTitle, StatusPill, TablePagination } from "@/components/cr/kit";
import { PageContainer, PageHeader } from "@/components/cr/page-header";
import { fmtDateTime, usePaged } from "@/components/cr/pages-table";
import { Markdown } from "@/components/cr/pages-markdown";
import { SectionError, TableSkeleton } from "@/components/cr/pages-skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { timeAgo } from "@/lib/format";
import { p8, qk8, useReportRun, useReportRuns, useReports } from "@/lib/phase8-api";
import type { ReportDef, ReportDefIn, ReportRunStatus, ReportSchedule } from "@/lib/phase8-types";
import { useOrg } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { Dropdown } from "@/components/cr/dropdown";

const RUN_TONE = { queued: "neutral", running: "warning", completed: "success", failed: "danger" } as const;

function RunStatus({ status }: { status: ReportRunStatus }) {
  return <StatusPill tone={RUN_TONE[status]}><span className="capitalize">{status}</span></StatusPill>;
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const EMPTY: ReportDefIn = {
  name: "Weekly digest", prompt: "", schedule: "weekly", hour_utc: 9, weekday: 0, repo_ids: [], email_to: [], enabled: true,
};

function scheduleLabel(r: ReportDef) {
  const at = `${String(r.hour_utc).padStart(2, "0")}:00 UTC`;
  if (r.schedule === "daily") return `Daily at ${at}`;
  if (r.schedule === "weekly") return `${WEEKDAYS[r.weekday]}s at ${at}`;
  return `1st of the month at ${at}`;
}

function CustomReport({ slug, onDone }: { slug: string; onDone: (id: string) => void }) {
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState("Summarize this week's security findings and which repositories need attention.");
  const [days, setDays] = useState(7);
  const m = useMutation({
    mutationFn: () => p8.customReport(slug, { prompt, days, repo_ids: [] }),
    onSuccess: (run) => {
      toast.success("Report queued — it appears below in a few seconds.");
      void qc.invalidateQueries({ queryKey: qk8.runs(slug) });
      onDone(run.id);
    },
    onError: toastError("Could not start the report."),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Sparkles aria-hidden className="size-4 text-muted-foreground" /> Custom report</CardTitle>
        <CardDescription>Ask for any summary of your review data. Reports are free; a few per day per organization.</CardDescription>
      </CardHeader>
      <CardContent>
        <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} maxLength={4000} aria-label="Report prompt" className="font-mono text-[13px] leading-relaxed" />
      </CardContent>
      <CardFooter className="flex-wrap justify-between gap-3 border-t bg-subtle">
        <Dropdown value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
          {[1, 7, 14, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </Dropdown>
        <Button onClick={() => m.mutate()} disabled={m.isPending || prompt.trim().length < 3}>
          {m.isPending ? <Loader2 aria-hidden className="animate-spin" /> : <Sparkles aria-hidden />} Generate
        </Button>
      </CardFooter>
    </Card>
  );
}

function FormSection({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 border-b px-5 py-6 last:border-b-0 sm:px-6">
      <div>
        <h3 className="text-sm font-medium">{title}</h3>
        {description ? <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ReportForm({ slug, initial, onClose, emailEnabled }: { slug: string; initial: ReportDef | null; onClose: () => void; emailEnabled: boolean }) {
  const qc = useQueryClient();
  const [f, setF] = useState<ReportDefIn>(initial ? { ...initial } : EMPTY);
  const [emails, setEmails] = useState((initial?.email_to ?? []).join(", "));
  const set = <K extends keyof ReportDefIn>(k: K, v: ReportDefIn[K]) => setF((p) => ({ ...p, [k]: v }));
  const [touched, setTouched] = useState(false);
  const nameError = touched && !f.name.trim() ? "Give the report a name." : null;
  const m = useMutation({
    mutationFn: () => {
      const body = { ...f, email_to: emails.split(/[,\s]+/).filter(Boolean) };
      return initial ? p8.updateReport(slug, initial.id, body) : p8.createReport(slug, body);
    },
    onSuccess: () => {
      toast.success("Report saved");
      void qc.invalidateQueries({ queryKey: qk8.reports(slug) });
      onClose();
    },
    onError: toastError("Could not save the report."),
  });
  return (
    <div className="flex flex-col">
      <PageHeader
        title={initial ? "Edit Report" : "Create Report"}
        description={initial ? initial.name : "Generated on a schedule and optionally emailed to your team."}
        actions={<>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => m.mutate()} disabled={m.isPending || !f.name.trim()}>
            {m.isPending ? <Loader2 aria-hidden className="animate-spin" /> : <CircleCheck aria-hidden />} {initial ? "Save" : "Create Report"}
          </Button>
        </>}
      />
      <div className="rounded-md border bg-card">
        <FormSection title="Name">
          <div className="flex max-w-md flex-col gap-1.5">
            <Input id="rn" aria-label="Name" placeholder="Enter the name here" value={f.name}
              aria-invalid={nameError ? true : undefined} aria-describedby={nameError ? "rn-err" : undefined}
              onBlur={() => setTouched(true)} onChange={(e) => { set("name", e.target.value); setTouched(true); }} />
            {nameError ? <span id="rn-err" className="text-xs text-destructive">{nameError}</span> : null}
          </div>
        </FormSection>
        <FormSection title="Schedule" description="Stick to a schedule so the team gets a steady picture of review activity over time.">
          <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label id="rs-l">Frequency</Label>
              <Segmented<ReportSchedule> value={f.schedule} onChange={(v) => set("schedule", v)} className="[&>div]:w-full [&_button]:flex-1"
                options={[{ value: "daily", label: "Daily" }, { value: "weekly", label: "Weekly" }, { value: "monthly", label: "Monthly" }]} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="rh">Time</Label>
                <Dropdown id="rh" className="w-full" value={f.hour_utc} onChange={(e) => set("hour_utc", Number(e.target.value))} aria-label="Hour (UTC)">
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
                </Dropdown>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="rtz">Timezone</Label>
                <Input id="rtz" value="UTC" readOnly disabled className="font-mono" />
              </div>
            </div>
            {f.schedule === "weekly" ? (
              <div className="flex flex-col gap-1.5 md:col-span-2">
                <Label id="rd-l">Day</Label>
                <div role="radiogroup" aria-labelledby="rd-l" className="flex flex-wrap gap-2">
                  {DAY_SHORT.map((d, i) => (
                    <button key={d} type="button" role="radio" aria-checked={f.weekday === i} aria-label={WEEKDAYS[i]}
                      onClick={() => set("weekday", i)}
                      className={cn("h-8 min-w-14 rounded-md border px-3 text-sm transition-colors hover:bg-accent",
                        f.weekday === i ? "border-primary bg-primary/10 font-medium text-primary hover:bg-primary/15" : "bg-card text-muted-foreground")}>
                      {d}
                    </button>
                  ))}
                </div>
              </div>
            ) : f.schedule === "monthly" ? (
              <p className="text-sm text-muted-foreground md:col-span-2">Runs on the 1st of every month.</p>
            ) : null}
          </div>
        </FormSection>
        <FormSection title="Prompt" description="Adjust the AI instructions to personalize the report.">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rp">Instructions (optional)</Label>
            <Textarea id="rp" rows={6} value={f.prompt} className="font-mono text-[13px] leading-relaxed"
              placeholder="Default: activity, key findings, acceptance and 3 recommendations."
              onChange={(e) => set("prompt", e.target.value)} />
          </div>
        </FormSection>
        <FormSection title="Delivery" description="Where the finished report goes. Reports are always stored on this page.">
          <div className="flex max-w-xl flex-col gap-1.5">
            <Label htmlFor="re">Email to (comma separated)</Label>
            <Input id="re" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="lead@example.com" />
            {!emailEnabled ? <span className="text-xs text-muted-foreground">Email delivery is off (SMTP_URL is not set); reports are still stored here.</span> : null}
          </div>
          <label className="flex items-center justify-between gap-4 rounded-md border px-4 py-3 text-sm sm:max-w-xl">
            <span>
              <span className="font-medium">Enabled</span>
              <span className="block text-muted-foreground">Paused reports keep their settings but do not run.</span>
            </span>
            <Switch checked={f.enabled} onCheckedChange={(v) => set("enabled", v)} aria-label="Enabled" />
          </label>
        </FormSection>
      </div>
    </div>
  );
}

function RunView({ slug, id }: { slug: string; id: string }) {
  const q = useReportRun(slug, id);
  const r = q.data;
  if (!r) return q.error ? <QueryState error={q.error} what="This report" className="h-40" /> : <Skeleton className="h-80" />;
  return (
    <Card className="min-w-0">
      <CardHeader className="border-b">
        <CardTitle>{r.title}</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-1 text-xs">
          <RunStatus status={r.status} />
          {r.degraded ? " · numbers only (narrative unavailable)" : ""}
          {r.emailed_to.length ? ` · emailed to ${r.emailed_to.join(", ")}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {r.content ? (
          <Markdown source={r.content} />
        ) : r.error ? (
          <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{r.error}</p>
        ) : (
          <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 aria-hidden className="size-4 animate-spin" /> Generating…</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function ReportsPage() {
  const { org: slug } = useParams<{ org: string }>();
  const qc = useQueryClient();
  const org = useOrg(slug);
  const isAdmin = org.data?.role === "admin";
  const defs = useReports(slug);
  const runs = useReportRuns(slug);
  const [editing, setEditing] = useState<ReportDef | "new" | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<ReportDef | null>(null);
  const runNow = useMutation({
    mutationFn: (id: string) => p8.runReport(slug, id),
    onSuccess: (run) => { toast.success("Report queued"); setSelected(run.id); void qc.invalidateQueries({ queryKey: qk8.runs(slug) }); },
    onError: toastError("Could not run the report."),
  });
  const del = useMutation({
    mutationFn: (id: string) => p8.deleteReport(slug, id),
    onSuccess: () => {
      toast.success("Report deleted");
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: qk8.reports(slug) });
    },
    onError: toastError("Could not delete the report."),
  });
  const current = selected ?? runs.data?.runs.find((r) => r.status === "completed")?.id ?? null;
  const reports = defs.data?.reports;
  const runList = runs.data?.runs;
  const pg = usePaged(reports ?? []);
  if (editing) {
    return (
      <PageContainer>
        <ReportForm slug={slug} initial={editing === "new" ? null : editing} onClose={() => setEditing(null)}
          emailEnabled={defs.data?.email_enabled ?? false} />
      </PageContainer>
    );
  }
  return (
    <PageContainer className="flex flex-col">
      <PageHeader
        title="Reports"
        description="AI summaries of your review activity — on demand, or delivered on a schedule."
        actions={isAdmin ? <Button onClick={() => setEditing("new")}><PlusCircle aria-hidden /> Create Report</Button> : null}
      />
      <section>
        <SectionTitle>Scheduled reports</SectionTitle>
        {defs.isPending ? <TableSkeleton cols={5} rows={2} rowHeight="h-[61px]" /> : defs.isError ? (
          <SectionError title="Could not load scheduled reports." error={defs.error} onRetry={() => void defs.refetch()} />
        ) : reports?.length === 0 ? (
          <EmptyState icon={CalendarClock} title="No scheduled reports yet"
            action={isAdmin ? <Button variant="outline" onClick={() => setEditing("new")}><PlusCircle aria-hidden /> Create Report</Button> : null}>
            Schedule a daily, weekly or monthly digest of reviews and findings.
          </EmptyState>
        ) : reports ? (
          <div>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Name</TableHead><TableHead>Schedule</TableHead><TableHead>Last run</TableHead><TableHead>Next run</TableHead>
                <TableHead>Status</TableHead>
                {isAdmin ? <TableHead><span className="sr-only">Actions</span></TableHead> : null}
              </TableRow></TableHeader>
              <TableBody>
                {pg.pageRows.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="max-w-0 min-w-48 sm:w-2/5">
                      <div className="truncate font-medium" title={r.name}>{r.name}</div>
                      <div className="text-xs text-muted-foreground">{r.email_to.length ? `${r.email_to.length} recipient(s)` : "Stored here only"}</div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{scheduleLabel(r)}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground" title={r.last_run_at ? new Date(r.last_run_at).toLocaleString() : undefined}>
                      {r.last_run_at ? timeAgo(r.last_run_at) : "Never"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{r.next_run_at ? fmtDateTime(r.next_run_at) : "—"}</TableCell>
                    <TableCell>{r.enabled ? <StatusPill tone="success">Active</StatusPill> : <StatusPill>Paused</StatusPill>}</TableCell>
                    {isAdmin ? (
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button variant="outline" size="sm" onClick={() => runNow.mutate(r.id)} disabled={runNow.isPending}>
                            {runNow.isPending && runNow.variables === r.id ? <Loader2 aria-hidden className="animate-spin" /> : <Play aria-hidden />} Run now
                          </Button>
                          <Button variant="ghost" size="icon-sm" className="text-muted-foreground" aria-label={`Edit ${r.name}`} onClick={() => setEditing(r)}><Pencil aria-hidden /></Button>
                          <Button variant="ghost" size="icon-sm" className="text-destructive hover:bg-destructive/10 hover:text-destructive" aria-label={`Delete ${r.name}`} onClick={() => setDeleting(r)}><Trash2 aria-hidden /></Button>
                        </div>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <TablePagination {...pg} />
          </div>
        ) : null}
      </section>
      <section className="mt-10">
        <SectionTitle>On-demand report</SectionTitle>
        <CustomReport slug={slug} onDone={setSelected} />
      </section>
      <section className="mt-10">
        <SectionTitle>Generated reports</SectionTitle>
        {runs.isPending ? (
          <div className="grid items-start gap-4 lg:grid-cols-[320px_1fr]"><Skeleton className="h-64" /><Skeleton className="h-80" /></div>
        ) : runs.isError ? (
          <SectionError title="Could not load generated reports." error={runs.error} onRetry={() => void runs.refetch()} />
        ) : runList?.length === 0 ? (
          <EmptyState icon={FileText} title="Nothing generated yet">
            Generate a custom report above, or run a scheduled one — results appear here.
          </EmptyState>
        ) : runList ? (
          <div className="grid items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
            <div className="flex max-h-[32rem] flex-col overflow-y-auto rounded-md border bg-card">
              {runList.map((r) => (
                <button key={r.id} type="button" onClick={() => setSelected(r.id)}
                  className={cn(
                    "relative border-b px-4 py-3 text-left text-sm transition-colors last:border-b-0 hover:bg-subtle",
                    current === r.id && "bg-subtle before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-primary",
                  )}>
                  <div className="truncate font-medium">{r.title}</div>
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <RunStatus status={r.status} /><span className="text-faint">·</span>
                    <span className="capitalize">{r.trigger}</span><span className="text-faint">·</span>
                    <span>{timeAgo(r.created_at)}</span>
                  </div>
                </button>
              ))}
            </div>
            {current ? <RunView slug={slug} id={current} /> : null}
          </div>
        ) : null}
      </section>
      <Dialog open={deleting !== null} onOpenChange={(o) => { if (!o) setDeleting(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this report?</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{deleting?.name}</span> will stop running. Reports it already generated stay on this page.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="destructive" disabled={del.isPending} onClick={() => deleting && del.mutate(deleting.id)}>
              {del.isPending ? <Loader2 aria-hidden className="animate-spin" /> : null}Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
