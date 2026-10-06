"use client";
import { Check, Copy, FileCode2, SearchX } from "lucide-react";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { EmptyState, SearchField } from "@/components/cr/dash-ui";
import { Button } from "@/components/ui/button";
import { CONFIG_FILE, referenceGroups, yamlValue, type RefField } from "@/lib/config-docs";
import type { ConfigSchema } from "@/lib/api-types";
import { cn } from "@/lib/utils";

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Copied");
    return true;
  } catch {
    toast.error("Could not copy to the clipboard.");
    return false;
  }
}

export function CopyButton({ text, label = "Copy", className }: { text: string; label?: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button type="button" variant="ghost" size="sm" aria-label={label}
      className={cn("h-7 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground", className)}
      onClick={async () => {
        if (await copyText(text)) {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        }
      }}>
      {done ? <Check aria-hidden className="size-3.5" /> : <Copy aria-hidden className="size-3.5" />}
      {label}
    </Button>
  );
}

/** Splits a trailing ` # comment` off a YAML line (quotes are not parsed; the guide's snippets don't need it). */
function splitComment(s: string): [string, string] {
  const i = s.indexOf(" #");
  return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i)];
}

function YamlLine({ line }: { line: string }) {
  if (/^\s*#/.test(line)) return <span className="text-faint">{line}</span>;
  const m = /^(\s*)(- )?([A-Za-z0-9_.$\-[\]]+)(:)(.*)$/.exec(line);
  if (!m) {
    const item = /^(\s*- )(.*)$/.exec(line);
    const [body, comment] = splitComment(item ? item[2]! : line);
    return (
      <>
        {item ? <span className="text-faint">{item[1]}</span> : null}
        <span className="text-foreground">{body}</span>
        <span className="text-faint">{comment}</span>
      </>
    );
  }
  const [, indent, dash, key, colon, rest] = m;
  const [value, comment] = splitComment(rest!);
  return (
    <>
      {indent}
      {dash ? <span className="text-faint">{dash}</span> : null}
      <span className="text-primary">{key}</span>
      <span className="text-faint">{colon}</span>
      <span className="text-foreground">{value}</span>
      <span className="text-faint">{comment}</span>
    </>
  );
}

/** A `.hootpr.yaml` snippet in a file frame with light key/comment highlighting and a copy button. */
export function YamlBlock({ code, title = CONFIG_FILE, className, maxHeight }: {
  code: string;
  title?: string;
  className?: string;
  maxHeight?: string;
}) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <div className={cn("overflow-hidden rounded-md border bg-surface", className)}>
      <div className="flex h-9 items-center gap-2 border-b bg-subtle pr-1 pl-3">
        <FileCode2 aria-hidden className="size-3.5 text-muted-foreground" />
        <span className="font-mono text-xs text-muted-foreground">{title}</span>
        <CopyButton text={code} className="ml-auto" />
      </div>
      <pre tabIndex={0} aria-label={`${title} example`}
        className={cn("overflow-auto p-3 font-mono text-xs leading-relaxed text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50", maxHeight)}>
        {lines.map((l, i) => (
          <Fragment key={i}>
            <YamlLine line={l} />
            {i < lines.length - 1 ? "\n" : null}
          </Fragment>
        ))}
      </pre>
    </div>
  );
}

export function InlineCode({ children }: { children: ReactNode }) {
  return <code className="rounded-sm bg-muted px-1 py-px font-mono text-[12px] text-foreground">{children}</code>;
}

function FieldRow({ f, groupPath }: { f: RefField; groupPath: string }) {
  const hasDefault = f.default !== undefined && !(Array.isArray(f.default) && f.default.length === 0 && f.type.startsWith("list"));
  const range = f.min !== undefined || f.max !== undefined
    ? `${f.min ?? "…"}–${f.max ?? "…"}` : null;
  return (
    <li className="flex flex-col gap-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <code className="font-mono text-[13px] font-medium break-all text-foreground" title={f.path}>
          {groupPath ? <span className="text-faint">{groupPath}.</span> : null}{f.key}
        </code>
        <span className="rounded-sm border px-1.5 font-mono text-[11px] leading-5 text-muted-foreground">{f.type}</span>
        {hasDefault ? (
          <span className="font-mono text-[11px] text-muted-foreground">
            default <span className="text-foreground">{yamlValue(f.default)}</span>
          </span>
        ) : null}
        {range ? <span className="font-mono text-[11px] text-muted-foreground">range {range}</span> : null}
      </div>
      {f.description ? <p className="text-[13px] leading-snug text-muted-foreground">{f.description}</p> : null}
      {f.options ? (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-faint">One of</span>
          {f.options.map((o) => (
            <code key={o} className="rounded-sm bg-muted px-1.5 font-mono text-[11px] leading-5 text-foreground">{o}</code>
          ))}
        </div>
      ) : null}
    </li>
  );
}

/** Every `.hootpr.yaml` key, grouped by the object it lives in, with a search box. */
export function ConfigReference({ schema }: { schema: ConfigSchema }) {
  const groups = useMemo(() => referenceGroups(schema), [schema]);
  const [q, setQ] = useState("");
  const query = q.trim().toLowerCase();
  const shown = query
    ? groups
        .map((g) => ({
          ...g,
          fields: g.fields.filter((f) =>
            `${f.path} ${f.description ?? ""} ${(f.options ?? []).join(" ")}`.toLowerCase().includes(query)),
        }))
        .filter((g) => g.fields.length)
    : groups;
  const total = groups.reduce((n, g) => n + g.fields.length, 0);
  const count = shown.reduce((n, g) => n + g.fields.length, 0);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <SearchField aria-label="Search settings" placeholder="Search keys and descriptions…" value={q}
          onChange={(e) => setQ(e.target.value)} className="w-full sm:w-80" />
        <span className="text-xs text-muted-foreground">{query ? `${count} of ${total}` : total} settings</span>
      </div>
      {shown.length === 0 ? (
        <EmptyState icon={SearchX} title="No matching settings">Try a key name such as path_filters or a word such as label.</EmptyState>
      ) : (
        shown.map((g) => (
          <section key={g.path} id={`ref-${g.path || "top"}`} aria-label={g.path || "Top level"}
            className="scroll-mt-20 overflow-hidden rounded-md border bg-card">
            <header className="border-b bg-subtle px-4 py-2.5">
              <h3 className="font-mono text-[13px] font-medium break-all">{g.path || "(top level)"}</h3>
              {g.description ? <p className="mt-0.5 text-xs text-muted-foreground">{g.description}</p> : null}
            </header>
            <ul className="divide-y">
              {g.fields.map((f) => <FieldRow key={f.path} f={f} groupPath={g.path} />)}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
