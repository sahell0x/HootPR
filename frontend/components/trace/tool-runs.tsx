import { Chip, type ChipTone } from "@/components/cr/review-chip";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ToolRun } from "@/lib/api-types";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE: Record<string, ChipTone> = { ok: "success", timeout: "caution", failed: "danger",
  unavailable: "faint", skipped: "faint" };

export function ToolRuns({ runs }: { runs: ToolRun[] }) {
  if (runs.length === 0) return <p className="py-4 text-sm text-muted-foreground">No tool runs recorded.</p>;
  return (
    <Table aria-label="Tool runs" className="[&_td]:py-2">
      <TableHeader><TableRow><TableHead>Tool</TableHead><TableHead>Status</TableHead><TableHead>Findings</TableHead>
        <TableHead>Duration</TableHead><TableHead>stderr</TableHead></TableRow></TableHeader>
      <TableBody>
        {runs.map((r) => (
          <TableRow key={r.id} className={cn(r.status === "skipped" || r.status === "unavailable" ? "text-muted-foreground" : "")}>
            <TableCell className="font-mono text-[0.8125rem]">{r.tool}</TableCell>
            <TableCell><Chip tone={TONE[r.status] ?? "neutral"} mono>{r.status}</Chip></TableCell>
            <TableCell className={cn("font-mono text-xs tabular-nums", r.findings_count === 0 && "text-faint")}>{r.findings_count}</TableCell>
            <TableCell className="font-mono text-xs tabular-nums text-muted-foreground">{formatMs(r.duration_ms)}</TableCell>
            <TableCell className="max-w-md truncate font-mono text-xs text-muted-foreground" title={r.stderr_excerpt ?? ""}>
              {r.stderr_excerpt ?? ""}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
