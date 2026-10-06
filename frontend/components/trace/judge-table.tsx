import { Chip } from "@/components/cr/review-chip";
import { SeverityBadge } from "@/components/severity-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Finding } from "@/lib/api-types";
import { formatPct, lineSpan } from "@/lib/format";

const VERDICT_TONE = { keep: "success", drop: "faint", merge: "info" } as const;

export function JudgeTable({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) return <p className="py-4 text-sm text-muted-foreground">No candidate findings.</p>;
  return (
    <Table aria-label="Judge verdicts" className="[&_td]:py-2">
      <TableHeader><TableRow><TableHead>Verdict</TableHead><TableHead>Finding</TableHead><TableHead>Severity</TableHead>
        <TableHead>Confidence</TableHead><TableHead>Reason</TableHead><TableHead>Posted</TableHead></TableRow></TableHeader>
      <TableBody>
        {findings.map((f) => (
          <TableRow key={f.id}>
            <TableCell>
              {f.judge_verdict ? (
                <Chip tone={VERDICT_TONE[f.judge_verdict as keyof typeof VERDICT_TONE] ?? "neutral"} mono>{f.judge_verdict}</Chip>
              ) : <span className="text-faint">—</span>}
            </TableCell>
            <TableCell className="max-w-80 min-w-56 whitespace-normal">
              <span className="line-clamp-2" title={f.title}>{f.title}</span>
              <div className="flex min-w-0 gap-1 font-mono text-xs text-muted-foreground">
                <span className="truncate" title={f.path}>{f.path}</span>
                <span className="shrink-0 whitespace-nowrap">· {lineSpan(f.start_line, f.end_line)}</span>
              </div>
            </TableCell>
            <TableCell><SeverityBadge severity={f.severity} /></TableCell>
            <TableCell className="font-mono text-xs tabular-nums">{formatPct(f.confidence)}</TableCell>
            <TableCell className="max-w-md min-w-48 text-xs whitespace-normal text-muted-foreground">{f.judge_reason ?? ""}</TableCell>
            <TableCell className={f.posted ? "font-mono text-xs text-success" : "font-mono text-xs text-faint"}>{f.posted ? "yes" : "no"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
