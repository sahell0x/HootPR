"use client";
import {
  BookOpen, Braces, ChevronRight, FileCode2, FolderTree, ListChecks, type LucideIcon, MessageSquare, RotateCcw,
  Settings2, Sparkles, SquareCheckBig, Wrench, Zap,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { sectionId, type SettingsNavItem } from "@/components/cr/settings-layout";
import { TopbarActions } from "@/components/cr/shell-slots";
import { FieldControl } from "@/components/field-control";
import { ObjectListEditor } from "@/components/object-list-editor";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { ConfigError } from "@/lib/api-types";
import { type ConfigSchema, type FieldNode, flattenSchema } from "@/lib/schema-form";
import { getPath, type Json, setPath, unsetPath } from "@/lib/settings-paths";
import { type GroupName, GROUPS, OPEN_GROUPS } from "@/lib/settings-ui";
import { cn } from "@/lib/utils";

/** Controls that need the full row width (rendered under their label). */
const WIDE_KINDS = new Set<FieldNode["kind"]>(["textarea", "list", "objectList"]);

const GROUP_ICONS: Record<GroupName, LucideIcon> = {
  General: Settings2,
  Reviews: ListChecks,
  "Auto review": Zap,
  "Path filters & instructions": FolderTree,
  "AST-grep": Braces,
  Tools: Wrench,
  "Pre-merge checks": SquareCheckBig,
  "Finishing touches": Sparkles,
  Chat: MessageSquare,
  "Knowledge base": BookOpen,
  "Code generation": FileCode2,
};

/** Groups nested under "Reviews" in the section tree (they all live under `reviews.*`). */
const REVIEW_CHILDREN: GroupName[] = ["Auto review", "Path filters & instructions", "AST-grep", "Tools"];

/** Section-tree entries for the schema groups that have at least one field, in display order. */
export function settingsGroupNav(schema: ConfigSchema): SettingsNavItem[] {
  const groups = new Set(flattenSchema(schema).map((f) => f.group));
  const item = (g: GroupName): SettingsNavItem => ({ id: sectionId(g), label: g, icon: GROUP_ICONS[g] });
  const nestReviews = groups.has("Reviews");
  return GROUPS.filter((g) => groups.has(g) && !(nestReviews && REVIEW_CHILDREN.includes(g))).map((g) =>
    g === "Reviews"
      ? { ...item(g), children: REVIEW_CHILDREN.filter((c) => groups.has(c)).map((c) => ({ id: sectionId(c), label: c })) }
      : item(g));
}

const errorsFor = (errors: ConfigError[], path: string) =>
  errors.filter((x) => x.path === path || x.path.startsWith(`${path}.`));

/**
 * Repository / organization settings rendered from the published `.hootpr.yaml` JSON schema
 * (contract C7). Only overridden keys are saved; keys the schema does not know survive untouched.
 */
export function SettingsForm({ schema, value, onSave, readOnly = false, errors = [], expandAll = false }: {
  schema: ConfigSchema; value: Json; onSave: (partial: Json) => Promise<void>; readOnly?: boolean; errors?: ConfigError[];
  /** "All Settings" mode: every group expanded. */
  expandAll?: boolean;
}) {
  const formId = useId();
  const nodes = useMemo(() => flattenSchema(schema), [schema]);
  const [draft, setDraft] = useState<Json>(value);
  const [generation, setGeneration] = useState(0);
  const [invalid, setInvalid] = useState<ReadonlySet<string>>(new Set());
  const [saving, setSaving] = useState(false);
  useEffect(() => { setDraft(value); setGeneration((g) => g + 1); }, [value]);

  const onValidityChange = useCallback((key: string, valid: boolean) => {
    setInvalid((prev) => {
      if (valid === !prev.has(key)) return prev;
      const next = new Set(prev);
      if (valid) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  const id = (f: FieldNode) => `field-${f.path.replaceAll(".", "-")}`;
  const unmatched = errors.filter((e) => !nodes.some((n) => e.path === n.path || e.path.startsWith(`${n.path}.`)));

  function row(f: FieldNode) {
    const current = getPath(draft, f.path);
    const overridden = current !== undefined;
    const shown = current ?? f.default;
    const set = (v: unknown) => setDraft((d) => (v === undefined ? unsetPath(d, f.path) : setPath(d, f.path, v)));
    const wide = WIDE_KINDS.has(f.kind) || Boolean(f.yaml);
    const fieldErrors = errorsFor(errors, f.path);
    return (
      <div key={f.path} className={cn(
        "flex flex-col gap-3 px-4 py-3.5",
        !wide && "sm:flex-row sm:items-center sm:justify-between sm:gap-8",
        f.kind === "bool" && "flex-row items-center justify-between gap-6",
      )}>
        <div className="min-w-0 sm:max-w-xl">
          <div className="flex flex-wrap items-center gap-2">
            <Label htmlFor={id(f)} className="text-sm font-medium">{f.label}</Label>
            {overridden ? (
              <span className="inline-flex h-5 items-center gap-1 rounded-sm border px-1.5 text-[11px] leading-none text-muted-foreground">
                <span aria-hidden className="size-1.5 rounded-full bg-primary" />Overridden
              </span>
            ) : (
              <span className="sr-only">Default</span>
            )}
          </div>
          {f.description ? <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{f.description}</p> : null}
        </div>
        <div className={cn("flex min-w-0 items-start gap-2", !wide && "sm:shrink-0 sm:items-center", f.kind === "bool" && "shrink-0")}>
          <div className={cn("min-w-0 flex-1", !wide && "sm:flex-none",
            fieldErrors.length > 0 && "[&_input]:border-destructive [&_select]:border-destructive [&_textarea]:border-destructive")}>
            {f.kind === "objectList" && f.item
              ? <ObjectListEditor field={f} id={id(f)} value={shown} onChange={set} readOnly={readOnly}
                  onValidityChange={onValidityChange} />
              : <FieldControl field={f} id={id(f)} label={f.label} value={shown} onChange={set} readOnly={readOnly}
                  onValidityChange={onValidityChange} />}
            {fieldErrors.map((e, i) => (
              <p key={i} className="mt-1.5 text-xs text-destructive">
                {e.path !== f.path ? `${e.path.slice(f.path.length + 1)}: ` : ""}{e.message}
              </p>
            ))}
          </div>
          {overridden && !readOnly ? (
            <Button type="button" variant="ghost" size="icon-sm" aria-label={`Reset ${f.label}`} title="Reset to default"
              className="text-muted-foreground hover:text-foreground" onClick={() => set(undefined)}>
              <RotateCcw aria-hidden />
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(value);
  const discard = () => { setDraft(value); setGeneration((g) => g + 1); };

  return (
    <form id={formId} className="flex flex-col gap-6" onSubmit={async (e) => {
      e.preventDefault();
      setSaving(true);
      try { await onSave(draft); } finally { setSaving(false); }
    }}>
      {unmatched.length ? (
        <Alert variant="destructive">
          <AlertDescription>
            <ul>{unmatched.map((e, i) => <li key={i}>{e.path ? `${e.path}: ` : ""}{e.message}</li>)}</ul>
          </AlertDescription>
        </Alert>
      ) : null}
      <div key={generation} className="flex flex-col gap-4">
        {GROUPS.map((g) => {
          const fields = nodes.filter((f) => f.group === g);
          if (!fields.length) return null;
          const open = expandAll || OPEN_GROUPS.includes(g)
            || fields.some((f) => getPath(value, f.path) !== undefined || errorsFor(errors, f.path).length > 0);
          const overrides = fields.filter((f) => getPath(draft, f.path) !== undefined).length;
          return (
            <details key={g} id={sectionId(g)} open={open}
              className="group/section scroll-mt-20 overflow-hidden rounded-md border bg-card">
              <summary className="flex cursor-pointer list-none items-center gap-2.5 px-4 py-3 text-[0.9375rem] font-medium tracking-tight select-none hover:bg-subtle [&::-webkit-details-marker]:hidden">
                <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform group-open/section:rotate-90" />
                {g}
                <span aria-hidden className="ml-auto flex items-center gap-2 font-mono text-[11px] font-normal text-faint">
                  {overrides ? <span className="text-primary">{overrides} overridden</span> : null}
                  <span>{fields.length} {fields.length === 1 ? "setting" : "settings"}</span>
                </span>
              </summary>
              <div className="divide-y border-t">{fields.map(row)}</div>
            </details>
          );
        })}
      </div>
      {!readOnly ? (
        <>
          {/* Top bar (CodeRabbit settings mode): the primary "Apply changes" action. */}
          <TopbarActions>
            <Button type="submit" form={formId} size="sm" disabled={!dirty || saving || invalid.size > 0}>
              {saving ? "Applying…" : "Apply changes"}
            </Button>
          </TopbarActions>
          {/* Compact sticky bar while there are unsaved edits (keeps Save reachable on small screens). When
              clean it is visually hidden but stays in the tab order and appears on keyboard focus. */}
          <div role="region" aria-label="Save settings"
            className={cn("sticky bottom-4 z-10 flex justify-end", !dirty && "sr-only focus-within:not-sr-only focus-within:sticky")}>
            <div className="flex max-w-full items-center gap-2 rounded-md border bg-popover py-1.5 pr-1.5 pl-3 shadow-lg shadow-black/20">
              {invalid.size ? (
                <p className="min-w-0 truncate text-[13px] text-destructive">Fix the invalid YAML before saving.</p>
              ) : (
                <p className="flex min-w-0 items-center gap-2 text-[13px] whitespace-nowrap text-muted-foreground">
                  <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", dirty ? "bg-caution" : "bg-faint")} />
                  {dirty ? "Unsaved changes" : "No unsaved changes"}
                </p>
              )}
              <Button type="button" variant="ghost" size="sm" disabled={!dirty || saving} onClick={discard}>Discard</Button>
              <Button type="submit" size="sm" disabled={saving || invalid.size > 0}>Save</Button>
            </div>
          </div>
        </>
      ) : null}
    </form>
  );
}
