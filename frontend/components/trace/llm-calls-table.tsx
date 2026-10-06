"use client";
import { Fragment, useState } from "react";
import { Chip } from "@/components/cr/review-chip";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { LlmCall, ReviewTask } from "@/lib/api-types";
import { formatMs, formatUsd } from "@/lib/format";
import { useLlmCall } from "@/lib/queries";

function Excerpts({ slug, reviewId, callId }: { slug: string; reviewId: string; callId: string }) {
  const { data, error } = useLlmCall(slug, reviewId, callId, true);
  if (error) return <p className="text-xs text-destructive">Could not load excerpts.</p>;
  if (!data) return <p className="text-xs text-muted-foreground">Loading…</p>;
  return (
    <div className="grid gap-2 whitespace-normal md:grid-cols-2">
      {([["Request", data.request_excerpt], ["Response", data.response_excerpt]] as const).map(([label, body]) => (
        <div key={label} className="min-w-0 overflow-hidden rounded-md border bg-surface">
          <div className="border-b px-3 py-1.5"><span className="eyebrow">{label}</span></div>
          <pre className="max-h-64 overflow-auto px-3 py-2 font-mono text-xs leading-5 whitespace-pre-wrap">{body ?? "(purged)"}</pre>
        </div>
      ))}
    </div>
  );
}

const NUM = "font-mono text-xs tabular-nums";

export function LlmCallsTable({ calls, tasks, slug, reviewId }:
  { calls: LlmCall[]; tasks: ReviewTask[]; slug: string; reviewId: string }) {
  const [open, setOpen] = useState<string | null>(null);
  if (calls.length === 0) return <p className="py-4 text-sm text-muted-foreground">No LLM calls recorded for this review.</p>;
  const taskTitle = new Map(tasks.map((t) => [t.id, t.title]));
  const sum = (k: "input_tokens" | "cached_tokens" | "output_tokens") => calls.reduce((a, c) => a + c[k], 0);
  const cost = calls.reduce((a, c) => a + (c.cost_usd ? Number(c.cost_usd) : 0), 0);
  return (
    <Table aria-label="LLM calls" className="[&_td]:py-2">
      <TableHeader><TableRow>
        <TableHead>Role</TableHead><TableHead>Model</TableHead><TableHead>Task</TableHead>
        <TableHead>Tokens (in / cached / out)</TableHead><TableHead>Cost</TableHead><TableHead>Latency</TableHead>
        <TableHead>Mode</TableHead><TableHead>Status</TableHead><TableHead />
      </TableRow></TableHeader>
      <TableBody>
        {calls.map((c) => (
          <Fragment key={c.id}>
            <TableRow>
              <TableCell className="text-[0.8125rem]">{c.role}</TableCell>
              <TableCell className="font-mono text-xs">{c.model}<div className="text-faint">{c.provider_host}</div></TableCell>
              <TableCell className="max-w-56 truncate text-xs text-muted-foreground">{c.task_id ? taskTitle.get(c.task_id) ?? "—" : "—"}</TableCell>
              <TableCell className={NUM}>{c.input_tokens} / {c.cached_tokens} / {c.output_tokens}</TableCell>
              <TableCell className={NUM}>{formatUsd(c.cost_usd)}</TableCell>
              <TableCell className={NUM}>{formatMs(c.latency_ms)}</TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{c.structured_mode ?? "—"}</TableCell>
              <TableCell>
                {c.status === "ok" ? <Chip tone="success" mono>ok</Chip> : (
                  <span className="block max-w-48 truncate text-xs text-destructive" title={c.error ?? c.status}>{c.error ?? c.status}</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <Button size="xs" variant="ghost" onClick={() => setOpen(open === c.id ? null : c.id)}
                        aria-label={`${open === c.id ? "Hide" : "Show"} request and response of call ${c.id}`}>
                  {open === c.id ? "Hide" : "Show request"}
                </Button>
              </TableCell>
            </TableRow>
            {open === c.id ? (
              <TableRow className="hover:bg-transparent"><TableCell colSpan={9} className="bg-subtle"><Excerpts slug={slug} reviewId={reviewId} callId={c.id} /></TableCell></TableRow>
            ) : null}
          </Fragment>
        ))}
        <TableRow className="bg-subtle font-medium hover:bg-subtle">
          <TableCell colSpan={3}>Total ({calls.length} calls)</TableCell>
          <TableCell className={NUM}>{sum("input_tokens")} / {sum("cached_tokens")} / {sum("output_tokens")}</TableCell>
          <TableCell className={NUM}>{cost > 0 ? `$${cost.toFixed(6)}` : "—"}</TableCell>
          <TableCell colSpan={4} />
        </TableRow>
      </TableBody>
    </Table>
  );
}
