"use client";
import { useEffect, useId, useRef, useState } from "react";
import { parse, stringify } from "yaml";
import { Textarea } from "@/components/ui/textarea";

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const toText = (v: unknown) => (v === undefined || v === null || v === "" ? "" : stringify(v));

/**
 * Edits a free-form object (e.g. an ast-grep `rule`) as YAML. Emits the parsed mapping on every
 * valid edit, `undefined` when emptied, and nothing while the text is invalid; validity is reported
 * to the form (which disables Save) and reset on unmount.
 */
export function YamlField({ id, label, value, onChange, readOnly = false, onValidityChange }: {
  id: string;
  label: string;
  value: unknown;
  onChange: (v: Record<string, unknown> | undefined) => void;
  readOnly?: boolean;
  onValidityChange?: (key: string, valid: boolean) => void;
}) {
  const key = useId();
  const [text, setText] = useState(() => toText(value));
  const [error, setError] = useState<string | null>(null);
  const [seen, setSeen] = useState(value);
  if (!same(value, seen)) {
    // Changed from outside (reset, reload): show it unless it is what this field just emitted.
    setSeen(value);
    let current: unknown;
    try { current = text.trim() ? parse(text) : undefined; } catch { current = Symbol("invalid"); }
    if (!same(current, value)) { setText(toText(value)); setError(null); }
  }

  const report = useRef(onValidityChange);
  useEffect(() => { report.current = onValidityChange; }, [onValidityChange]);
  useEffect(() => { report.current?.(key, error === null); }, [key, error]);
  useEffect(() => () => report.current?.(key, true), [key]);

  function edit(next: string) {
    setText(next);
    if (!next.trim()) { setError(null); setSeen(undefined); onChange(undefined); return; }
    let parsed: unknown;
    try { parsed = parse(next); } catch (e) {
      setError(`Invalid YAML: ${e instanceof Error ? e.message.split("\n")[0] : String(e)}`);
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setError("Invalid YAML: expected a mapping such as `pattern: print($A)`");
      return;
    }
    setError(null);
    setSeen(parsed);
    onChange(parsed as Record<string, unknown>);
  }

  return (
    <div className="flex flex-col gap-1">
      <Textarea id={id} aria-label={label} aria-invalid={error ? true : undefined} disabled={readOnly} rows={3}
        spellCheck={false} className="bg-surface font-mono text-xs leading-relaxed md:text-xs dark:bg-surface" value={text} onChange={(e) => edit(e.target.value)} />
      {error ? <p className="font-mono text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
