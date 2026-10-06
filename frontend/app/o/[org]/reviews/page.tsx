"use client";
import { ChevronsDownUp, ChevronsUpDown, GitPullRequest, SearchX } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { EmptyState, ListSkeleton, SearchField } from "@/components/cr/dash-ui";
import { Segmented } from "@/components/cr/kit";
import { PageHeader } from "@/components/cr/page-header";
import { DashedButton, OutcomeFilter, PrGroup, SortButton, TimelineTable } from "@/components/cr/review-log";
import { QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import type { ReviewStatus, ReviewSummary } from "@/lib/api-types";
import { useReviews } from "@/lib/queries";

type View = "prs" | "timeline";

export default function ReviewsPage() {
  const { org: slug } = useParams<{ org: string }>();
  const q = useReviews(slug);
  const rows = useMemo(() => q.data?.pages.flatMap((p) => p.reviews) ?? [], [q.data]);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<View>("prs");
  const [dir, setDir] = useState<"desc" | "asc">("desc");
  const [outcomes, setOutcomes] = useState<ReviewStatus[]>([]);
  // null = default (first pull request expanded, like the Review Log)
  const [expanded, setExpanded] = useState<Set<string> | null>(null);
  // Tokens / LLM cost are internal: the API only returns them to platform owners.
  const internal = rows.some((r) => r.input_tokens != null);

  const counts = useMemo(() => {
    const c: Partial<Record<ReviewStatus, number>> = {};
    for (const r of rows) c[r.status] = (c[r.status] ?? 0) + 1;
    return c;
  }, [rows]);

  const needle = search.trim().toLowerCase();
  const shown = useMemo(() => {
    const list = rows.filter(
      (r) =>
        (outcomes.length === 0 || outcomes.includes(r.status)) &&
        (!needle || `${r.pr_title} ${r.repo_full_name}#${r.pr_number} ${r.repo_full_name} #${r.pr_number}`.toLowerCase().includes(needle)),
    );
    return list.sort((a, b) => (dir === "desc" ? b.created_at.localeCompare(a.created_at) : a.created_at.localeCompare(b.created_at)));
  }, [rows, outcomes, needle, dir]);

  const groups = useMemo(() => {
    const m = new Map<string, ReviewSummary[]>();
    for (const r of shown) {
      const k = `${r.repo_full_name}#${r.pr_number}`;
      const g = m.get(k);
      if (g) g.push(r);
      else m.set(k, [r]);
    }
    return [...m.entries()];
  }, [shown]);

  const isOpen = (k: string) => (expanded ? expanded.has(k) : k === groups[0]?.[0]);
  const toggle = (k: string) => {
    const next = new Set(expanded ?? (groups[0] ? [groups[0][0]] : []));
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setExpanded(next);
  };
  const filtered = needle || outcomes.length > 0;
  const allOpen = groups.length > 0 && groups.every(([k]) => isOpen(k));
  const clearFilters = () => {
    setSearch("");
    setOutcomes([]);
  };

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Reviews"
        description="Every pull request HootPR has reviewed in this organization, and each review event on it."
      />
      {q.isError && rows.length === 0 ? (
        <QueryState error={q.error} what="These reviews" />
      ) : q.isSuccess && rows.length === 0 ? (
        <EmptyState icon={GitPullRequest} title="No reviews yet" className="py-14">
          Open a pull request on an enabled repository and HootPR&apos;s review events will show up here.
        </EmptyState>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <Segmented<View>
              value={view}
              onChange={setView}
              options={[{ value: "prs", label: "Pull requests" }, { value: "timeline", label: "Timeline" }]}
            />
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
              {view === "prs" && groups.length > 1 ? (
                <DashedButton
                  onClick={() => setExpanded(allOpen ? new Set() : new Set(groups.map(([k]) => k)))}
                  aria-label={allOpen ? "Collapse all pull requests" : "Expand all pull requests"}
                >
                  {allOpen ? <ChevronsDownUp aria-hidden /> : <ChevronsUpDown aria-hidden />}
                  {allOpen ? "Collapse all" : "Expand all"}
                </DashedButton>
              ) : null}
              <SortButton dir={dir} onToggle={() => setDir((d) => (d === "desc" ? "asc" : "desc"))} />
              <OutcomeFilter value={outcomes} onChange={setOutcomes} counts={counts} />
              <SearchField
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search pull requests"
                aria-label="Search reviews"
                className="sm:w-72"
              />
            </div>
          </div>
          {q.isPending ? (
            <ListSkeleton />
          ) : shown.length === 0 && rows.length > 0 ? (
            <EmptyState
              icon={SearchX}
              title="No matching reviews"
              className="py-10"
              action={<Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>}
            >
              {needle ? <>No reviews match “{search}”.</> : "No reviews match this outcome filter."}
            </EmptyState>
          ) : view === "prs" ? (
            <div className="border-t-2 border-border">
              {groups.map(([k, reviews]) => (
                <PrGroup key={k} slug={slug} reviews={reviews} open={isOpen(k)} onToggle={() => toggle(k)} internal={internal} />
              ))}
            </div>
          ) : (
            <TimelineTable slug={slug} reviews={shown} internal={internal} />
          )}
          {filtered && q.hasNextPage ? (
            <p className="mt-3 text-center text-xs text-faint">Filters apply to the reviews loaded so far.</p>
          ) : null}
        </>
      )}
      {q.hasNextPage ? (
        <Button variant="outline" className="mt-4 self-center" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
          {q.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      ) : null}
    </div>
  );
}
