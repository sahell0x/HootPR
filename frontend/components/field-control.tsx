"use client";
import { useState } from "react";
import { SettingsSelect } from "@/components/cr/settings-select";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { YamlField } from "@/components/yaml-field";
import type { FieldNode } from "@/lib/schema-form";
import { splitList } from "@/lib/settings-paths";

export interface ControlProps {
  field: FieldNode;
  id: string;
  /** Accessible name of the control. */
  label: string;
  /** The value to show (the override, else the default). */
  value: unknown;
  /** `undefined` unsets the key. */
  onChange: (v: unknown) => void;
  readOnly?: boolean;
  onValidityChange?: (key: string, valid: boolean) => void;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Comma/newline separated list; keeps the typed text while it still means the same list. */
function ListInput({ id, label, value, onChange, readOnly }: Omit<ControlProps, "field">) {
  const list = Array.isArray(value) ? value.map(String) : [];
  const [text, setText] = useState(() => list.join(", "));
  const [seen, setSeen] = useState(list);
  if (!same(list, seen)) {
    setSeen(list);
    if (!same(splitList(text), list)) setText(list.join(", "));
  }
  return (
    <Textarea id={id} aria-label={label} disabled={readOnly} rows={2} value={text} spellCheck={false}
      placeholder="Comma or newline separated" className="font-mono text-[13px] md:text-[13px]"
      onChange={(e) => {
        const next = splitList(e.target.value);
        setText(e.target.value);
        setSeen(next);
        onChange(next);
      }} />
  );
}

export function FieldControl({ field, id, label, value, onChange, readOnly = false, onValidityChange }: ControlProps) {
  if (field.yaml || field.kind === "objectList")
    return <YamlField id={id} label={label} value={value} readOnly={readOnly} onValidityChange={onValidityChange}
      onChange={onChange} />;
  if (field.kind === "bool")
    return <Switch id={id} aria-label={label} checked={Boolean(value)} disabled={readOnly} onCheckedChange={onChange} />;
  if (field.kind === "select")
    return (
      <SettingsSelect id={id} aria-label={label} disabled={readOnly} value={value == null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}>
        {value == null ? <option value="" disabled>Choose…</option> : null}
        {field.options?.map((o) => <option key={o} value={o}>{o}</option>)}
      </SettingsSelect>
    );
  if (field.kind === "list")
    return <ListInput id={id} label={label} value={value} onChange={onChange} readOnly={readOnly} />;
  if (field.kind === "number")
    return <Input id={id} aria-label={label} type="number" disabled={readOnly} className="w-full font-mono tabular-nums sm:w-32"
      value={typeof value === "number" ? String(value) : ""}
      onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />;
  const text = value == null ? "" : String(value);
  if (field.kind === "textarea")
    return <Textarea id={id} aria-label={label} disabled={readOnly} rows={3} value={text}
      onChange={(e) => onChange(e.target.value)} />;
  return <Input id={id} aria-label={label} disabled={readOnly} value={text} className="w-full sm:w-72"
    onChange={(e) => onChange(e.target.value)} />;
}
