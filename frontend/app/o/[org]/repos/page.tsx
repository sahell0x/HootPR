"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FolderGit2, GitBranch, Globe, Lock, Plus, RefreshCw, Search, Settings2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { BulkBar, FilterSelect, SortableHead, StatusPill, TablePagination } from "@/components/cr/kit";
import { PageContainer, PageHeader } from "@/components/cr/page-header";
import { QueryState } from "@/components/query-state";
import { ProviderIcon } from "@/components/cr/settings-provider-icon";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import type { Repo } from "@/lib/api-types";
import { timeAgo } from "@/lib/format";
import { qk, useOrg, useRepos } from "@/lib/queries";
import { useOrgSlug } from "@/lib/use-org-slug";

type StatusFilter = "all" | "enabled" | "disabled";
type SortKey = "name" | "status";

const FILTERS = [
  { value: "all", label: "All repositories" },
  { value: "enabled", label: "Enabled" },
  { value: "disabled", label: "Disabled" },
] as const;

/** "group/sub/repo" → ["group / sub /", "repo"] */
function splitName(fullName: string): [string, string] {
  const i = fullName.lastIndexOf("/");
  if (i < 0) return ["", fullName];
  return [`${fullName.slice(0, i).split("/").join(" / ")} /`, fullName.slice(i + 1)];
}

export default function ReposPage() {
  const slug = useOrgSlug();
  const qc = useQueryClient();
  const org = useOrg(slug);
  const repos = useRepos(slug);
  const isAdmin = org.data?.role === "admin";
  const provider = org.data?.provider;

  const toggle = useMutation({
    mutationFn: (r: Repo) => api.updateRepo(slug, r.id, { enabled: !r.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.repos(slug) }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not update the repository."),
  });
  const sync = useMutation({
    mutationFn: () => api.syncRepos(slug),
    onSuccess: () => {
      toast.success("Sync queued. New repositories appear in a few seconds.");
      setTimeout(() => void qc.invalidateQueries({ queryKey: qk.repos(slug) }), 4000);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Sync failed."),
  });

  const list = useMemo(() => repos.data?.repos ?? [], [repos.data]);
  const installUrl = repos.data?.install_url;
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "name", dir: "asc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [bulkPending, setBulkPending] = useState(false);

  const q = query.trim().toLowerCase();
  const shown = useMemo(() => {
    const rows = list.filter((r) =>
      (!q || r.full_name.toLowerCase().includes(q))
      && (status === "all" || (status === "enabled") === r.enabled));
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const byName = a.full_name.localeCompare(b.full_name);
      if (sort.key === "status" && a.enabled !== b.enabled) return (a.enabled ? -1 : 1) * dir;
      return sort.key === "name" ? byName * dir : byName;
    });
  }, [list, q, status, sort]);
  const pageCount = Math.max(1, Math.ceil(shown.length / pageSize));
  const current = Math.min(page, pageCount);
  const pageRows = shown.slice((current - 1) * pageSize, current * pageSize);
  const enabledCount = list.filter((r) => r.enabled).length;

  const sortBy = (key: SortKey) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === "asc" ? "desc" : "asc" }));
  const sortedState = (key: SortKey) => (sort.key === key ? sort.dir : false);

  const selectedRepos = list.filter((r) => selected.has(r.id));
  const allOnPage = pageRows.length > 0 && pageRows.every((r) => selected.has(r.id));
  const someOnPage = pageRows.some((r) => selected.has(r.id));
  const toggleRow = (id: string, on: boolean) =>
    setSelected((s) => { const n = new Set(s); if (on) n.add(id); else n.delete(id); return n; });
  const togglePage = (on: boolean) =>
    setSelected((s) => { const n = new Set(s); for (const r of pageRows) { if (on) n.add(r.id); else n.delete(r.id); } return n; });

  /** Bulk enable/disable: runs the same per-repo toggle mutation for every selected repo that needs it. */
  async function bulk(enable: boolean) {
    const targets = selectedRepos.filter((r) => r.enabled !== enable);
    setBulkPending(true);
    try {
      const results = await Promise.allSettled(targets.map((r) => toggle.mutateAsync(r)));
      const ok = results.filter((x) => x.status === "fulfilled").length;
      if (ok) toast.success(`${enable ? "Enabled" : "Disabled"} ${ok} ${ok === 1 ? "repository" : "repositories"}`);
      setSelected(new Set());
    } finally {
      setBulkPending(false);
    }
  }

  return (
    <TooltipProvider>
    <PageContainer>
      <PageHeader
        title="Repositories"
        info="Every repository HootPR can see through your GitHub App installation or GitLab bot. Enabled repositories get a review on every pull request."
        description="List of repositories accessible to HootPR."
        actions={isAdmin ? (
          <>
            {provider === "github" && installUrl && list.length ? (
              <a className={buttonVariants({ variant: "outline" })} href={installUrl}>
                <Plus aria-hidden /> Add repositories
              </a>
            ) : null}
            {provider === "gitlab" && !org.data?.installed && list.length ? (
              <Link className={buttonVariants({ variant: "outline" })} href={`/o/${slug}/settings#gitlab`}>
                Connect GitLab bot
              </Link>
            ) : null}
            <Button variant="outline" onClick={() => sync.mutate()} disabled={sync.isPending}>
              <RefreshCw aria-hidden className={sync.isPending ? "animate-spin" : undefined} /> Sync Repositories
            </Button>
          </>
        ) : null}
      />

      {repos.isLoading ? (
        <div aria-busy="true" className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-44" />
            <Skeleton className="h-8 w-full sm:w-64" />
          </div>
          <div className="overflow-hidden rounded-md border">
            <div className="h-10 border-b bg-subtle" />
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="flex items-center gap-4 border-b px-3 py-3 last:border-b-0">
                <Skeleton className="size-4 shrink-0" />
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-3.5 w-44 max-w-full" />
                </div>
                <Skeleton className="hidden h-5 w-16 rounded-full sm:block" />
                <Skeleton className="h-5 w-9 rounded-full" />
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {repos.error ? <QueryState error={repos.error} what="This organization" backHref="/orgs" /> : null}

      {repos.data && list.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-md border border-dashed px-6 py-16 text-center">
          <span className="grid size-10 place-items-center rounded-md border bg-card text-muted-foreground">
            <FolderGit2 aria-hidden className="size-5" />
          </span>
          <div className="flex max-w-md flex-col gap-1">
            <h2 className="text-[0.9375rem] font-medium tracking-tight">No repositories yet</h2>
            <p className="text-sm text-muted-foreground">
              {!isAdmin
                ? "Ask an organization admin to connect repositories to HootPR."
                : provider === "gitlab"
                  ? "Connect a GitLab bot token in Settings, then pick the projects HootPR should review."
                  : "Install the HootPR GitHub App on this account and choose repositories. They show up here once GitHub confirms the installation."}
            </p>
          </div>
          {isAdmin && provider === "github" && installUrl ? (
            <a className={buttonVariants({ size: "sm", className: "mt-1" })} href={installUrl}>
              <Plus aria-hidden /> Install on GitHub
            </a>
          ) : null}
          {isAdmin && provider === "gitlab" && !org.data?.installed ? (
            <Link className={buttonVariants({ size: "sm", className: "mt-1" })} href={`/o/${slug}/settings#gitlab`}>
              Connect GitLab bot
            </Link>
          ) : null}
        </div>
      ) : null}

      {list.length > 0 ? (
        <div className="flex flex-col gap-3 pb-20">
          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect label="Show" value={status} options={FILTERS}
              onChange={(v) => { setStatus(v as StatusFilter); setPage(1); }} />
            <div className="relative w-full sm:w-64">
              <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input type="search" aria-label="Search repositories" placeholder="Search repositories" value={query}
                onChange={(e) => { setQuery(e.target.value); setPage(1); }} className="h-8 pl-8" />
            </div>
            <p className="ml-auto font-mono text-xs text-muted-foreground">
              <span className="text-foreground">{enabledCount}</span> of {list.length} enabled
            </p>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                {isAdmin ? (
                  <TableHead className="w-10">
                    <Checkbox aria-label="Select all repositories on this page"
                      checked={allOnPage ? true : someOnPage ? "indeterminate" : false}
                      onCheckedChange={(c) => togglePage(c === true)} />
                  </TableHead>
                ) : null}
                <SortableHead sorted={sortedState("name")} onSort={() => sortBy("name")}>Repository</SortableHead>
                <SortableHead className="hidden sm:table-cell" sorted={sortedState("status")} onSort={() => sortBy("status")}>Status</SortableHead>
                <TableHead className="hidden lg:table-cell">Branch</TableHead>
                <TableHead className="hidden lg:table-cell">Visibility</TableHead>
                <TableHead className="hidden md:table-cell">Last review</TableHead>
                <TableHead className="w-px">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageRows.map((r) => {
                const [path, name] = splitName(r.full_name);
                const isSel = selected.has(r.id);
                return (
                  <TableRow key={r.id} data-state={isSel ? "selected" : undefined}>
                    {isAdmin ? (
                      <TableCell>
                        <Checkbox aria-label={`Select ${r.full_name}`} checked={isSel}
                          onCheckedChange={(c) => toggleRow(r.id, c === true)} />
                      </TableCell>
                    ) : null}
                    <TableCell className="w-full max-w-0 py-2.5">
                      <span className="flex min-w-0 items-center gap-2.5">
                        <ProviderIcon provider={r.provider} className="hidden shrink-0 text-muted-foreground sm:block" />
                        <span className="flex min-w-0 flex-col">
                          <span className="sr-only">{r.full_name}</span>
                          <span aria-hidden className="truncate text-xs text-muted-foreground">{path}</span>
                          <span aria-hidden className="truncate font-medium">{name}</span>
                        </span>
                      </span>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <StatusPill tone={r.enabled ? "success" : "neutral"}>{r.enabled ? "Enabled" : "Disabled"}</StatusPill>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <span title={r.default_branch} className="inline-flex max-w-48 items-center gap-1 font-mono text-xs text-muted-foreground">
                        <GitBranch aria-hidden className="size-3 shrink-0" />
                        <span className="truncate">{r.default_branch}</span>
                      </span>
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground lg:table-cell">
                      <span className="inline-flex items-center gap-1.5 text-[13px]">
                        {r.private ? <Lock aria-hidden className="size-3.5" /> : <Globe aria-hidden className="size-3.5" />}
                        {r.private ? "Private" : "Public"}
                      </span>
                    </TableCell>
                    <TableCell className="hidden text-[13px] whitespace-nowrap text-muted-foreground md:table-cell">
                      {r.last_review_at ? timeAgo(r.last_review_at) : "—"}
                    </TableCell>
                    <TableCell>
                      <span className="flex items-center justify-end gap-2">
                        <Switch
                          checked={r.enabled}
                          disabled={!isAdmin || toggle.isPending}
                          aria-label={`Enable ${r.full_name}`}
                          onCheckedChange={() => toggle.mutate(r, {
                            onSuccess: () => toast.success(`${r.enabled ? "Disabled" : "Enabled"} reviews for ${r.full_name}`),
                          })}
                        />
                        <Link
                          className={buttonVariants({ variant: "ghost", size: "sm", className: "text-muted-foreground hover:text-foreground" })}
                          href={`/o/${slug}/repos/${r.id}/settings`}
                        >
                          <Settings2 aria-hidden className="hidden sm:block" />
                          <span className="sr-only sm:not-sr-only">Settings</span>
                          <ChevronRight aria-hidden />
                        </Link>
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
              {shown.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={7} className="py-10 text-center text-sm whitespace-normal text-muted-foreground">
                    <span className="flex flex-col items-center gap-2">
                      <Search aria-hidden className="size-4 text-faint" />
                      {q ? `No repositories match “${query}”.` : "No repositories with this status."}
                      <Button type="button" variant="outline" size="sm"
                        onClick={() => { setQuery(""); setStatus("all"); setPage(1); }}>Clear filters</Button>
                    </span>
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
          <TablePagination page={current} pageCount={pageCount} onPage={setPage} pageSize={pageSize}
            onPageSize={(n) => { setPageSize(n); setPage(1); }} className="mt-0" />
        </div>
      ) : null}

      {isAdmin ? (
        <BulkBar count={selectedRepos.length} onClear={() => setSelected(new Set())}>
          <Button size="sm" disabled={bulkPending} onClick={() => void bulk(true)}>Enable</Button>
          <Button size="sm" variant="outline" disabled={bulkPending} onClick={() => void bulk(false)}>Disable</Button>
        </BulkBar>
      ) : null}
    </PageContainer>
    </TooltipProvider>
  );
}
