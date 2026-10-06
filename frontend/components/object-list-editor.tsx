"use client";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { FieldControl } from "@/components/field-control";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { FieldNode } from "@/lib/schema-form";
import { getPath, type Json, setPath, unsetPath } from "@/lib/settings-paths";
import { singularOf } from "@/lib/settings-ui";

let nextRowId = 0;
const newIds = (n: number) => Array.from({ length: n }, () => nextRowId++);

/** A list of objects (path instructions, ast-grep rules, custom checks, ...), one fieldset per element. */
export function ObjectListEditor({ field, id, value, onChange, readOnly = false, onValidityChange }: {
  field: FieldNode;
  id: string;
  value: unknown;
  onChange: (v: Json[]) => void;
  readOnly?: boolean;
  onValidityChange?: (key: string, valid: boolean) => void;
}) {
  const rows: Json[] = Array.isArray(value) ? value.map((r) => (r && typeof r === "object" ? (r as Json) : {})) : [];
  const [ids, setIds] = useState(() => newIds(rows.length));
  if (ids.length !== rows.length) setIds(newIds(rows.length)); // replaced from outside (reset, reload)
  const singular = singularOf(field.label);
  const noun = singular.toLowerCase();
  const items = field.item ?? [];

  const update = (i: number, row: Json) => onChange(rows.map((r, j) => (j === i ? row : r)));

  return (
    <div id={id} className="flex flex-col gap-3">
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed px-3 py-3 text-center text-[13px] text-muted-foreground">None.</p>
      ) : null}
      {rows.map((row, i) => (
        <fieldset key={ids[i] ?? i} className="min-w-0 overflow-hidden rounded-md border bg-background/40">
          <div className="flex h-10 items-center justify-between border-b bg-subtle pr-1.5 pl-3">
            <legend className="float-left font-mono text-xs text-muted-foreground">
              <span className="text-foreground">{singular}</span> {i + 1}
            </legend>
            {!readOnly ? (
              <Button type="button" variant="ghost" size="sm" aria-label={`Remove ${noun} ${i + 1}`}
                className="text-muted-foreground hover:text-destructive"
                onClick={() => { setIds(ids.filter((_, j) => j !== i)); onChange(rows.filter((_, j) => j !== i)); }}>
                <Trash2 aria-hidden className="size-4" /> Remove
              </Button>
            ) : null}
          </div>
          <div className="flex flex-col gap-3 p-3">
          {items.map((it) => {
            const cid = `${id}-${ids[i] ?? i}-${it.path.replaceAll(".", "-")}`;
            const current = getPath(row, it.path);
            return (
              <div key={it.path} className="grid gap-1.5 md:grid-cols-[168px_minmax(0,1fr)] md:items-start md:gap-4">
                <div className="md:pt-1.5">
                  <Label htmlFor={cid} className="text-[13px]">{it.label}</Label>
                  {it.description ? <p className="mt-0.5 text-xs text-muted-foreground">{it.description}</p> : null}
                </div>
                <FieldControl field={it} id={cid} label={`${singular} ${i + 1} ${it.path}`} readOnly={readOnly}
                  value={current ?? it.default} onValidityChange={onValidityChange}
                  onChange={(v) => update(i, v === undefined || v === "" ? unsetPath(row, it.path) : setPath(row, it.path, v))} />
              </div>
            );
          })}
          </div>
        </fieldset>
      ))}
      {!readOnly ? (
        <Button type="button" variant="outline" size="sm" className="self-start"
          onClick={() => { setIds([...ids, ...newIds(1)]); onChange([...rows, {}]); }}>
          <Plus aria-hidden className="size-4" /> Add {noun}
        </Button>
      ) : null}
    </div>
  );
}
