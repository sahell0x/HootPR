import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Tiny, safe Markdown renderer for generated reports: headings, paragraphs, bullet / numbered
 * lists, pipe tables, **bold**, *italic* and `code`. Builds React elements only (never raw HTML).
 */
function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0] ?? "";
    const k = `${key}-${i++}`;
    if (t.startsWith("**")) out.push(<strong key={k} className="font-medium text-foreground">{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k} className="rounded-sm bg-muted px-1 font-mono text-[0.8125rem] break-all text-foreground">{t.slice(1, -1)}</code>);
    else out.push(<em key={k}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = (row: string) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function Markdown({ source, className }: { source: string; className?: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const at = (n: number) => lines[n] ?? "";
  const blocks: ReactNode[] = [];
  let i = 0;
  let b = 0;
  while (i < lines.length) {
    const line = at(i);
    const key = `b${b++}`;
    if (!line.trim()) { i++; continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const level = (h[1] ?? "").length;
      const text = h[2] ?? "";
      const cls = level <= 2 ? "mt-6 text-base font-medium first:mt-0" : "mt-5 text-sm font-medium first:mt-0";
      blocks.push(level <= 2 ? <h3 key={key} className={cls}>{inline(text, key)}</h3> : <h4 key={key} className={cls}>{inline(text, key)}</h4>);
      i++;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(at(i + 1))) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(at(i))) rows.push(cells(at(i++)));
      blocks.push(
        <div key={key} className="my-3 overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-subtle"><tr>{head.map((c, j) => <th key={j} className="border-b px-3 py-2 text-left font-medium text-muted-foreground">{inline(c, `${key}h${j}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri} className="border-b last:border-b-0">{r.map((c, j) => <td key={j} className="px-3 py-2 tabular-nums">{inline(c, `${key}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    const ul = /^\s*[-*+]\s+/;
    const ol = /^\s*\d+[.)]\s+/;
    if (ul.test(line) || ol.test(line)) {
      const ordered = ol.test(line);
      const re = ordered ? ol : ul;
      const items: string[] = [];
      while (i < lines.length && re.test(at(i))) items.push(at(i++).replace(re, ""));
      const List = ordered ? "ol" : "ul";
      blocks.push(
        <List key={key} className={cn("my-2 flex flex-col gap-1 pl-5", ordered ? "list-decimal" : "list-disc")}>
          {items.map((t, j) => <li key={j}>{inline(t, `${key}-${j}`)}</li>)}
        </List>,
      );
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && at(i).trim() && !/^(#{1,4}\s|\s*[-*+]\s|\s*\d+[.)]\s|\s*\|)/.test(at(i))) para.push(at(i++));
    if (!para.length) para.push(at(i++));
    blocks.push(<p key={key} className="my-2">{inline(para.join(" "), key)}</p>);
  }
  return <div className={cn("text-sm leading-relaxed [overflow-wrap:anywhere] text-foreground/90", className)}>{blocks}</div>;
}
