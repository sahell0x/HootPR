"use client";
import { AlertTriangle, ExternalLink, FileCode2, FileWarning, Send } from "lucide-react";
import { useParams } from "next/navigation";
import { type CSSProperties, useEffect, useMemo, useState } from "react";
import { CommentComposer, ReviewPanel } from "@/components/phase8/cs-actions";
import { CsChat } from "@/components/phase8/cs-chat";
import { DiffSkeleton, DiffViewer } from "@/components/phase8/diff-viewer";
import { QueryState } from "@/components/query-state";
import { SEVERITY_LABEL } from "@/components/severity-badge";
import { CsLayersNav } from "@/components/cr/cs-layers";
import { CollapsibleSection, useViewportFill } from "@/components/cr/cs-section";
import { TopbarTitle } from "@/components/cr/shell-slots";
import { Button } from "@/components/ui/button";
import { type CsTone, DotChip } from "@/components/cr/cs-pull-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { lineSpan, shortSha, timeAgo } from "@/lib/format";
import { useCsFile, useWorkspace } from "@/lib/phase8-api";
import type { CsFile, CsReviewComment } from "@/lib/phase8-types";
import { cn } from "@/lib/utils";
import { Dropdown } from "@/components/cr/dropdown";

const SEVERITY_TONE: Record<string, CsTone> = { critical: "destructive", major: "primary", minor: "caution", nitpick: "muted" };

export default function ChangeStackPage() {
  const { org: slug, pr } = useParams<{ org: string; pr: string }>();
  const [sha, setSha] = useState<string | null>(null);
  const ws = useWorkspace(slug, pr, sha);
  const [file, setFile] = useState<CsFile | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [reveal, setReveal] = useState<number | null>(null);
  const [pending, setPending] = useState<CsReviewComment[]>([]);
  const [open, setOpen] = useState({ changes: true, review: true });
  const chatBox = useViewportFill<HTMLDivElement>();
  const data = ws.data;
  const viewSha = data?.snapshot?.head_sha ?? data?.pull.head_sha ?? "";

  useEffect(() => {
    if (!data) return;
    const all = data.groups.flatMap((g) => g.files);
    if (!file || !all.some((f) => f.path === file.path)) setFile(all[0] ?? null);
  }, [data, file]);

  const contents = useCsFile(slug, pr, viewSha, file);
  const fileFindings = useMemo(() => (data?.findings ?? []).filter((f) => f.path === file?.path), [data, file]);

  if (!data) {
    return ws.error ? (
      <QueryState error={ws.error} what="This pull request" backHref={`/o/${slug}/change-stack`} />
    ) : (
      <WorkspaceSkeleton />
    );
  }
  const p = data.pull;

  const dir = file?.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/") + 1) : "";
  const base = file?.path.slice(dir.length) ?? "";

  const files = data.groups.reduce((n, g) => n + g.files.length, 0);
  const toggle = (k: keyof typeof open) => (v: boolean) => setOpen((o) => ({ ...o, [k]: v }));
  const goToReview = () => {
    setOpen((o) => ({ ...o, review: true }));
    requestAnimationFrame(() => document.getElementById("cs-review")?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  };

  return (
    <div className="xl:-my-8 xl:-mr-8 xl:grid xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className={cn("flex min-w-0 flex-col gap-6 pb-6 xl:py-8 xl:pr-8", pending.length && "pb-24 xl:pb-24")}>
        <header className="flex flex-col gap-3 pt-1">
          <TopbarTitle>{p.title}</TopbarTitle>
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="min-w-0 flex-1 basis-80">
              <h1 className="text-2xl font-medium tracking-tight break-words">
                {p.title} <span className="font-normal text-faint">#{p.number}</span>
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted-foreground">
                <DotChip tone={p.state === "open" ? "success" : p.state === "merged" ? "primary" : "muted"} className="capitalize">
                  {p.state}{p.is_draft ? " · draft" : ""}
                </DotChip>
                <span className="inline-flex min-w-0 flex-wrap items-center gap-1">
                  @{p.author_username} wants to merge
                  <code className="rounded-sm border bg-subtle px-1 font-mono text-xs text-foreground/85">{p.head_ref}</code>
                  into
                  <code className="rounded-sm border bg-subtle px-1 font-mono text-xs text-foreground/85">{p.base_ref}</code>
                </span>
                <a href={p.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                  Open on {p.provider === "gitlab" ? "GitLab" : "GitHub"} <ExternalLink className="size-3" />
                </a>
              </div>
            </div>
            <label className="flex w-full items-center gap-2 text-[13px] text-muted-foreground sm:w-auto">
              <span>Snapshot</span>
              <Dropdown className="min-w-0 flex-1 font-mono text-xs sm:max-w-[26rem]" value={data.snapshot?.head_sha ?? ""} onChange={(e) => setSha(e.target.value || null)}>
                {data.snapshots.length === 0 ? <option value="">Not reviewed yet (live diff)</option> : null}
                {data.snapshots.map((s) => (
                  <option key={s.head_sha} value={s.head_sha}>
                    {shortSha(s.head_sha)} · {s.trigger} · {s.findings} findings · {timeAgo(s.created_at)}{s.stale ? " · stale" : " · current"}
                  </option>
                ))}
              </Dropdown>
            </label>
          </div>
        </header>
        {data.stale ? (
          <Alert>
            <AlertTriangle aria-hidden />
            <AlertDescription>
              This snapshot is stale: the pull request head is now {shortSha(p.head_sha)}. Findings reflect {shortSha(viewSha)}; comment
              <code className="mx-1">@hootpr review</code> on the PR for an incremental review.
            </AlertDescription>
          </Alert>
        ) : null}
        {data.diff_error ? (
          <Alert variant="destructive">
            <FileWarning aria-hidden />
            <AlertDescription>{data.diff_error}</AlertDescription>
          </Alert>
        ) : null}

        <CollapsibleSection id="cs-changes" title="Changes" count={files} open={open.changes} onOpenChange={toggle("changes")} bodyClassName="overflow-hidden">
          <div className="grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[248px_minmax(0,1fr)]">
            <div className="relative min-w-0 border-b lg:border-r lg:border-b-0">
              {/* On lg the nav is absolutely filled so the diff column sets the row height and the nav scrolls. */}
              <div className="lg:absolute lg:inset-0">
                <CsLayersNav bare groups={data.groups} active={file?.path ?? null} onSelect={(f) => { setFile(f); setReveal(null); }} />
              </div>
            </div>
            <section aria-label="Diff" className="flex min-w-0 flex-col">
              <div className="flex h-10 shrink-0 items-center gap-2 border-b px-3">
                <FileCode2 className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate font-mono text-xs" title={file?.path}>
                  {file ? (<><span className="text-faint">{dir}</span><span className="text-foreground">{base}</span></>) : <span className="text-muted-foreground">Select a file</span>}
                  {contents.data?.truncated ? <span className="text-caution"> (truncated)</span> : ""}
                </span>
                {file ? (
                  <span className="flex shrink-0 items-center gap-2 font-mono text-[11px]">
                    <span className="text-success">+{file.additions}</span>
                    <span className="text-destructive">−{file.deletions}</span>
                    {file.status ? <span className="hidden rounded-sm border px-1 capitalize text-muted-foreground sm:inline">{file.status}</span> : null}
                  </span>
                ) : null}
              </div>
              <div className="h-[460px] shrink-0 lg:h-[560px]">
                {file && contents.data ? (
                  <DiffViewer
                    path={`${viewSha}/${file.path}`}
                    original={contents.data.original}
                    modified={contents.data.modified}
                    language={contents.data.language}
                    findings={fileFindings}
                    revealLine={reveal}
                    onCursorLine={setCursor}
                  />
                ) : file && contents.error ? (
                  <div role="alert" className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
                    <FileWarning className="size-5 text-destructive" aria-hidden />
                    <p className="text-sm font-medium">Could not load this file</p>
                    <p className="max-w-sm text-[13px] text-muted-foreground">{contents.error.message}</p>
                  </div>
                ) : file ? (
                  <DiffSkeleton />
                ) : null}
              </div>
              {fileFindings.length ? (
                <div className="shrink-0 border-t">
                  <div className="flex h-9 items-center gap-2 px-3">
                    <span className="text-[13px] font-medium">Findings in this file</span>
                    <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm bg-muted px-1 font-mono text-[11px] text-muted-foreground">{fileFindings.length}</span>
                  </div>
                  <ul className="max-h-48 overflow-y-auto border-t">
                    {fileFindings.map((f) => (
                      <li key={f.id} className="border-b last:border-b-0">
                        <button type="button" onClick={() => setReveal(f.end_line)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs transition-colors hover:bg-accent/60">
                          <DotChip tone={SEVERITY_TONE[f.severity] ?? "muted"} className="shrink-0">{SEVERITY_LABEL[f.severity] ?? f.severity}</DotChip>
                          <span className="shrink-0 font-mono text-faint">{lineSpan(f.start_line, f.end_line)}</span>
                          <span className="min-w-0 flex-1 truncate text-foreground">{f.title}</span>
                          <span className="hidden shrink-0 font-mono text-[11px] text-muted-foreground sm:inline">{f.status}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <CommentComposer path={file?.path ?? null} line={cursor} onAdd={(c) => setPending((x) => [...x, c])} />
            </section>
          </div>
        </CollapsibleSection>

        <CollapsibleSection
          id="cs-review"
          title="Your review"
          count={pending.length || undefined}
          open={open.review}
          onOpenChange={toggle("review")}
          bodyClassName="overflow-hidden"
        >
          <ReviewPanel slug={slug} pr={pr} ws={data} pending={pending}
            onRemove={(i) => setPending((x) => x.filter((_, j) => j !== i))} onDone={() => setPending([])} />
        </CollapsibleSection>
      </div>

      <aside aria-label="Chat" className="overflow-hidden rounded-lg border bg-card xl:overflow-visible xl:rounded-none xl:border-0 xl:border-l xl:bg-transparent">
        <div
          ref={chatBox.ref}
          className="h-[560px] xl:sticky xl:top-0 xl:h-[var(--fill,100dvh)]"
          style={chatBox.height ? ({ "--fill": `${chatBox.height}px` } as CSSProperties) : undefined}
        >
          <CsChat slug={slug} pr={pr} path={file?.path ?? null} line={cursor} headSha={viewSha} />
        </div>
      </aside>

      {pending.length ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-6 z-40 flex justify-center px-4 xl:pr-[400px]">
          <div className="pointer-events-auto flex items-center gap-2 rounded-lg border bg-popover p-1.5 shadow-lg shadow-black/30">
            <span className="rounded-md border border-dashed px-3 py-1.5 text-sm">
              {pending.length} {pending.length === 1 ? "comment" : "comments"} pending
            </span>
            <Button size="sm" onClick={goToReview}>
              <Send aria-hidden /> Submit review
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Loading placeholder shaped like the workspace: title, meta, Changes card (layers + diff), chat column. */
function WorkspaceSkeleton() {
  return (
    <div aria-busy="true" className="xl:-my-8 xl:-mr-8 xl:grid xl:grid-cols-[minmax(0,1fr)_400px]">
      <TopbarTitle>Pull request</TopbarTitle>
      <div className="flex min-w-0 flex-col gap-6 pb-6 xl:py-8 xl:pr-8">
        <div className="flex flex-col gap-3 pt-1">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-5 w-1/2" />
          <Skeleton className="h-8 w-80 max-w-full" />
        </div>
        <Skeleton className="h-7 w-32" />
        <div className="grid overflow-hidden rounded-lg border bg-card lg:grid-cols-[248px_minmax(0,1fr)]">
          <div className="flex flex-col gap-2 border-b p-3 lg:border-r lg:border-b-0">
            {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-5" style={{ width: `${55 + ((i * 23) % 40)}%` }} />)}
          </div>
          <Skeleton className="h-[460px] rounded-none lg:h-[560px]" />
        </div>
      </div>
      <div className="hidden border-l xl:flex xl:flex-col xl:gap-4 xl:p-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}
