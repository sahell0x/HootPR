import { Fragment, type ReactNode } from "react";

/**
 * Tiny, dependency-free markdown renderer for chat answers: fenced code blocks, headings, lists,
 * blockquotes, paragraphs, and inline `code` / **bold** / *italic* / [links](https://…).
 * Everything is rendered as React text nodes (no HTML injection).
 */
function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    const k = `${key}-${i++}`;
    if (m[1]) out.push(<code key={k} className="rounded-sm border bg-subtle px-1 py-px font-mono text-[12px] break-all">{t.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k} className="font-medium text-foreground">{t.slice(2, -2)}</strong>);
    else if (m[3]) out.push(<em key={k}>{t.slice(1, -1)}</em>);
    else {
      const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t) ?? [];
      out.push(<a key={k} href={href} target="_blank" rel="noreferrer" className="text-primary hover:underline">{label}</a>);
    }
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function CsMarkdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const at = (j: number) => lines[j] ?? "";
  const blocks: ReactNode[] = [];
  let i = 0;
  let n = 0;
  while (i < lines.length) {
    const line = at(i);
    const k = `b${n++}`;
    const fence = /^\s*```(\S*)/.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(at(i))) body.push(at(i++));
      i++;
      blocks.push(
        <div key={k} className="overflow-hidden rounded-md border bg-background">
          {fence[1] ? <div className="border-b px-3 py-1 font-mono text-[11px] text-faint">{fence[1]}</div> : null}
          <pre className="overflow-x-auto px-3 py-2 font-mono text-[12px] leading-relaxed"><code>{body.join("\n")}</code></pre>
        </div>,
      );
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push(<p key={k} className={(h[1] ?? "").length <= 2 ? "text-[15px] font-medium text-foreground" : "font-medium text-foreground"}>{inline(h[2] ?? "", k)}</p>);
      i++;
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(at(i))) body.push(at(i++).replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={k} className="border-l-2 pl-3 text-muted-foreground">{inline(body.join(" "), k)}</blockquote>);
      continue;
    }
    const listRe = /^\s*([-*+]|\d+[.)])\s+(.*)$/;
    if (listRe.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (i < lines.length && listRe.test(at(i))) items.push(listRe.exec(at(i++))?.[2] ?? "");
      const cls = "flex flex-col gap-1 pl-5 marker:text-faint";
      blocks.push(
        ordered ? (
          <ol key={k} className={`list-decimal ${cls}`}>{items.map((t, j) => <li key={j}>{inline(t, `${k}-${j}`)}</li>)}</ol>
        ) : (
          <ul key={k} className={`list-disc ${cls}`}>{items.map((t, j) => <li key={j}>{inline(t, `${k}-${j}`)}</li>)}</ul>
        ),
      );
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && at(i).trim() && !/^\s*(```|>|#{1,4}\s)/.test(at(i)) && !listRe.test(at(i))) para.push(at(i++));
    blocks.push(
      <p key={k}>
        {para.map((t, j) => (
          <Fragment key={j}>{j ? <br /> : null}{inline(t, `${k}-${j}`)}</Fragment>
        ))}
      </p>,
    );
  }
  return <div className="flex min-w-0 flex-col gap-2.5 break-words">{blocks}</div>;
}
