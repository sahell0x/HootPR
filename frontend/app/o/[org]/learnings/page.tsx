"use client";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ListFilter, Loader2, Plus, SearchX, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { EmptyState, SearchField } from "@/components/cr/dash-ui";
import { SectionError, TableSkeleton } from "@/components/cr/pages-skeleton";
import { PageContainer, PageHeader } from "@/components/cr/page-header";
import { StatGrid, StatTile } from "@/components/cr/stat-tile";
import { LearningDialog } from "@/components/learning-dialog";
import { LearningsTable } from "@/components/learnings-table";
import { QueryState } from "@/components/query-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, ApiError } from "@/lib/api";
import type { Learning } from "@/lib/api-types";
import { qk, useLearnings, useOrg, useRepos } from "@/lib/queries";
import { Dropdown } from "@/components/cr/dropdown";

function useDebounced<V>(value: V, ms: number): V {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setOut(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return out;
}

type DialogState = { kind: "closed" } | { kind: "create" } | { kind: "edit"; learning: Learning };

export default function LearningsPage() {
  const { org: slug } = useParams<{ org: string }>();
  const qc = useQueryClient();
  const org = useOrg(slug);
  const repos = useRepos(slug);
  const [search, setSearch] = useState("");
  const [repoId, setRepoId] = useState("");
  const q = useDebounced(search.trim(), 300);
  const list = useLearnings(slug, { repoId: repoId || undefined, q: q || undefined });
  const [dialog, setDialog] = useState<DialogState>({ kind: "closed" });
  const [deleting, setDeleting] = useState<Learning | null>(null);
  const [busy, setBusy] = useState(false);

  if (!org.data) return <QueryState error={org.error} what="This organization" backHref="/orgs" />;
  const optedOut = org.data.knowledge_base_opt_out;
  const isAdmin = org.data.role === "admin";
  const rows = list.data?.pages.flatMap((p) => p.learnings) ?? [];
  const repoList = repos.data?.repos ?? [];
  const filtered = Boolean(q || repoId);
  const more = list.hasNextPage ? "+" : "";
  const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
  const stats = {
    total: rows.length,
    org: rows.filter((l) => l.scope === "org").length,
    repo: rows.filter((l) => l.scope === "repo").length,
    week: rows.filter((l) => new Date(l.created_at).getTime() >= weekAgo).length,
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.deleteLearning(slug, deleting.id);
      toast.success("Learning deleted");
      setDeleting(null);
      await qc.invalidateQueries({ queryKey: qk.learningsAll(slug) });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not delete the learning.");
    } finally {
      setBusy(false);
    }
  };

  const repoName = repoList.find((r) => r.id === repoId)?.full_name;
  return (
    <PageContainer className="flex flex-col gap-4">
      <PageHeader
        className="mb-0 sm:flex-nowrap"
        title="Learnings"
        description={
          <>
            HootPR learns from your team&apos;s replies to improve future reviews. Search, filter, and manage your learnings below.
          </>
        }
        actions={isAdmin && !optedOut ? (
          <Button onClick={() => setDialog({ kind: "create" })}>
            <Plus aria-hidden /> Add learning
          </Button>
        ) : null}
      />

      {optedOut ? (
        <Alert>
          <AlertTitle>Learnings are off</AlertTitle>
          <AlertDescription>
            <span>
              Learnings are turned off for this organization. Turn them back on in{" "}
              <Link className="text-primary underline-offset-4 hover:underline" href={`/o/${slug}/settings`}>Settings → Knowledge base</Link>.
            </span>
          </AlertDescription>
        </Alert>
      ) : null}

      <StatGrid className="mb-0 grid-cols-2 lg:grid-cols-4">
        <StatTile label={filtered ? "Matching learnings" : "Total learnings"} value={list.isPending ? "—" : `${stats.total}${more}`} />
        <StatTile label="Organization-wide" value={list.isPending ? "—" : `${stats.org}${more}`} />
        <StatTile label="Repo-scoped" value={list.isPending ? "—" : `${stats.repo}${more}`} />
        <StatTile label="Created this week" value={list.isPending ? "—" : `${stats.week}${more}`} />
      </StatGrid>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <SearchField aria-label="Search learnings" placeholder="Search learnings…"
          value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="flex items-center gap-2">
          {repoName ? (
            <span className="inline-flex h-8 max-w-56 items-center gap-1.5 rounded-md border border-dashed px-2.5 text-sm">
              <span className="text-muted-foreground">Repository:</span>
              <span className="truncate font-mono text-xs">{repoName}</span>
              <button type="button" aria-label="Clear repository filter" onClick={() => setRepoId("")}
                className="text-muted-foreground hover:text-foreground">
                <X className="size-3.5" aria-hidden />
              </button>
            </span>
          ) : null}
          {/* "Filters" trigger: the outline button is the dropdown's visible face; its menu is the filter popover. */}
          <label className="relative inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border bg-card pr-2 pl-2.5 text-sm font-medium hover:bg-accent focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
            <ListFilter className="size-4 text-muted-foreground" aria-hidden />
            Filters
            {repoId ? <span className="rounded-sm bg-primary/15 px-1 font-mono text-[11px] text-primary">1</span> : null}
            <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden />
            <Dropdown aria-label="Repository" value={repoId} onChange={(e) => setRepoId(e.target.value)}
              className="absolute inset-0 cursor-pointer opacity-0" align="end">
              <option value="">All repositories</option>
              {repoList.map((r) => <option key={r.id} value={r.id}>{r.full_name}</option>)}
            </Dropdown>
          </label>
        </div>
      </div>

      {list.isPending ? (
        <TableSkeleton cols={4} rows={5} rowHeight="h-[67px]" />
      ) : list.isError ? (
        <SectionError title="Could not load learnings." error={list.error} onRetry={() => void list.refetch()} />
      ) : rows.length === 0 ? (
        optedOut ? null : filtered ? (
          <EmptyState icon={SearchX} title="No results"
            action={<Button variant="outline" size="sm" onClick={() => { setSearch(""); setRepoId(""); }}>Clear filters</Button>}>
            No learnings match these filters.
          </EmptyState>
        ) : (
          <EmptyState icon={BookOpen} title="Nothing learned yet"
            action={isAdmin ? (
              <Button variant="outline" onClick={() => setDialog({ kind: "create" })} aria-label="Add a learning manually">
                <Plus aria-hidden /> Add one manually
              </Button>
            ) : null}>
            No learnings yet. Reply to a HootPR review comment with a preference — for example “we use print() for CLI output here” — and HootPR will remember it.
          </EmptyState>
        )
      ) : (
        <LearningsTable slug={slug} isAdmin={isAdmin} learnings={rows}
          onEdit={(l) => setDialog({ kind: "edit", learning: l })} onDelete={setDeleting}
          footer={
            <>
              <span>
                <span className="font-medium text-foreground tabular-nums">{rows.length}</span>
                {list.hasNextPage ? " loaded — more available" : rows.length === 1 ? " learning" : " learnings"}
              </span>
              {list.hasNextPage ? (
                <Button variant="outline" size="sm" onClick={() => void list.fetchNextPage()}
                  disabled={list.isFetchingNextPage}>
                  Load more
                </Button>
              ) : null}
            </>
          } />
      )}

      <LearningDialog slug={slug} repos={repoList} open={dialog.kind !== "closed"}
        initial={dialog.kind === "edit" ? dialog.learning : undefined}
        onOpenChange={(open) => { if (!open) setDialog({ kind: "closed" }); }} />

      <Dialog open={deleting !== null} onOpenChange={(open) => { if (!open) setDeleting(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this learning?</DialogTitle>
            <DialogDescription>
              HootPR will stop applying it to reviews and chat answers. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {deleting ? <blockquote className="border-l-2 pl-3 text-sm">{deleting.text}</blockquote> : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="destructive" disabled={busy} onClick={() => void confirmDelete()}>
              {busy ? <Loader2 aria-hidden className="animate-spin" /> : null}Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
