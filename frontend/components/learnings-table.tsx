"use client";
import { ChevronRight, Pencil, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { SortableHead, TablePagination } from "@/components/cr/kit";
import { fmtDate, sortRows, usePaged, useSort } from "@/components/cr/pages-table";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Learning } from "@/lib/api-types";

export const SCOPE_LABEL: Record<Learning["scope"], string> = { repo: "Repository", org: "Organization" };

type SortKey = "created" | "updated";

export function LearningsTable({
  isAdmin,
  learnings,
  onEdit,
  onDelete,
  footer,
}: {
  slug: string;
  isAdmin: boolean;
  learnings: Learning[];
  onEdit: (l: Learning) => void;
  onDelete: (l: Learning) => void;
  /** Rendered left of the pagination (e.g. "Load more"). */
  footer?: ReactNode;
}) {
  const { sort, toggle, sorted } = useSort<SortKey>();
  const rows = sortRows(learnings, sort, (l, k) => (k === "created" ? l.created_at : l.updated_at));
  const pg = usePaged(rows);
  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Learning</TableHead>
            <TableHead>Source</TableHead>
            <SortableHead sorted={sorted("created")} onSort={() => toggle("created")}>Created at</SortableHead>
            <SortableHead sorted={sorted("updated")} onSort={() => toggle("updated")}>Updated at</SortableHead>
            <TableHead className="w-px"><span className="sr-only">Actions</span></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pg.pageRows.map((l) => (
            <TableRow key={l.id} className={isAdmin ? "group cursor-pointer" : "group"}
              onClick={isAdmin ? () => onEdit(l) : undefined}>
              <TableCell className="w-full max-w-0 min-w-64">
                <p className="truncate" title={l.text}>{l.text}</p>
                <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs whitespace-nowrap text-muted-foreground">
                  <span className="shrink-0 rounded-sm border px-1.5 leading-4">{SCOPE_LABEL[l.scope]}</span>
                  {l.repo_full_name ? <span className="max-w-full truncate font-mono" title={l.repo_full_name}>{l.repo_full_name}</span> : null}
                  {l.path_glob ? <span className="max-w-full truncate font-mono text-faint" title={l.path_glob}>{l.path_glob}</span> : null}
                  <span className="text-faint">·</span>
                  <span className="max-w-48 truncate" title={l.created_by_username}>{l.created_by_username}</span>
                  {l.embedded ? null : (
                    <span className="shrink-0 rounded-sm border border-caution/40 px-1.5 leading-4 text-caution"
                      title="HootPR is still indexing this learning; it will apply to reviews shortly.">
                      Indexing…
                    </span>
                  )}
                </div>
              </TableCell>
              <TableCell className="whitespace-nowrap">
                {l.source_url ? (
                  <a className="text-sm text-primary underline-offset-4 hover:underline" href={l.source_url}
                    target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                    {l.pr_number != null ? `PR #${l.pr_number}` : "Source"}
                  </a>
                ) : (
                  <span className="text-muted-foreground">Dashboard</span>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap" title={new Date(l.created_at).toLocaleString()}>
                {fmtDate(l.created_at)}
              </TableCell>
              <TableCell className="whitespace-nowrap" title={new Date(l.updated_at).toLocaleString()}>
                {fmtDate(l.updated_at)}
              </TableCell>
              <TableCell className="pr-3">
                <div className="flex items-center justify-end gap-0.5">
                  {isAdmin ? (
                    <>
                      <Button variant="ghost" size="icon-sm" aria-label="Edit learning"
                        className="text-muted-foreground opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                        onClick={(e) => { e.stopPropagation(); onEdit(l); }}>
                        <Pencil aria-hidden />
                      </Button>
                      <Button variant="ghost" size="icon-sm" aria-label="Delete learning"
                        className="text-muted-foreground opacity-100 hover:text-destructive sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                        onClick={(e) => { e.stopPropagation(); onDelete(l); }}>
                        <Trash2 aria-hidden />
                      </Button>
                      <ChevronRight aria-hidden className="ml-1 size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                    </>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">{footer}</div>
        <TablePagination className="mt-0" {...pg} />
      </div>
    </div>
  );
}
