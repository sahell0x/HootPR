"use client";
import { ChevronDown, GitPullRequest } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { CsBoard, CsColumn, CsPullCard } from "@/components/cr/cs-pull-card";
import { FilterSelect } from "@/components/cr/kit";
import { PageHeader } from "@/components/cr/page-header";
import { QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { CsPull } from "@/lib/phase8-types";
import { usePulls } from "@/lib/phase8-api";

export default function ChangeStackListPage() {
  const { org: slug } = useParams<{ org: string }>();
  const [state, setState] = useState("open");
  const q = usePulls(slug, state);
  const pulls = q.data?.pulls ?? [];
  const needs = pulls.filter((p) => p.last_reviewed_sha !== p.head_sha);
  const current = pulls.filter((p) => p.last_reviewed_sha != null && p.last_reviewed_sha === p.head_sha);
  const empty = (what: string) => (
    <p className="rounded-lg border border-dashed px-3 py-8 text-center text-xs text-muted-foreground">{what}</p>
  );
  const cards = (list: CsPull[], none: string) =>
    list.length ? <ColumnCards list={list} slug={slug} key={state} /> : empty(none);
  return (
    <div className="flex flex-col">
      <PageHeader
        title="Change Stack"
        description={
          <span className="block max-w-2xl">
            Review a pull request without leaving HootPR: files grouped by the review plan, the diff with HootPR&apos;s findings inline,
            a pinned chat about the change, and submitting your review or merging with your own account.
          </span>
        }
        actions={
          <FilterSelect
            label="State"
            value={state}
            onChange={setState}
            options={[{ value: "open", label: "Open" }, { value: "merged", label: "Merged" }, { value: "closed", label: "Closed" }]}
          />
        }
      />
      {!q.data && !q.error ? (
        <BoardSkeleton />
      ) : !q.data ? (
        <QueryState error={q.error} what="Pull requests" />
      ) : pulls.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed px-6 py-14 text-center">
          <GitPullRequest className="size-5 text-muted-foreground" aria-hidden />
          <p className="text-sm font-medium">Nothing in the stack</p>
          <p className="text-sm text-muted-foreground">No {state} pull requests seen by HootPR yet.</p>
        </div>
      ) : (
        <CsBoard>
          <CsColumn title="Needs review" caption="Not reviewed yet, or new commits since the last review" count={needs.length}>
            {cards(needs, "All caught up.")}
          </CsColumn>
          <CsColumn title="Reviewed" caption="HootPR's review matches the current head" count={current.length}>
            {cards(current, "No up-to-date reviews.")}
          </CsColumn>
        </CsBoard>
      )}
    </div>
  );
}

const PAGE = 10;

/** One column's cards, 10 at a time with a "Show more" footer (client-side over the loaded list). */
function ColumnCards({ list, slug }: { list: CsPull[]; slug: string }) {
  const [shown, setShown] = useState(PAGE);
  const rest = list.length - shown;
  return (
    <>
      {list.slice(0, shown).map((p) => <CsPullCard key={p.id} p={p} href={`/o/${slug}/change-stack/${p.id}`} />)}
      {rest > 0 ? (
        <Button variant="outline" size="sm" className="self-center" onClick={() => setShown((n) => n + PAGE)}>
          <ChevronDown aria-hidden /> Show {Math.min(rest, PAGE)} more
          <span className="font-mono text-[11px] text-faint">({rest} left)</span>
        </Button>
      ) : null}
    </>
  );
}

function BoardSkeleton() {
  const col = (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex flex-col gap-1.5 px-1 pb-1">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-3 w-56 max-w-full" />
      </div>
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="flex flex-col gap-2.5 rounded-lg border bg-card p-3.5">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-3 w-3/5" />
          <Skeleton className="h-3 w-2/5" />
        </div>
      ))}
    </div>
  );
  return (
    <div aria-busy="true" className="grid overflow-hidden rounded-lg border max-lg:divide-y lg:grid-cols-2 lg:divide-x">
      {col}
      {col}
    </div>
  );
}
