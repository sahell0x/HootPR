"use client";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import type { Learning, LearningScope, Repo } from "@/lib/api-types";
import { qk } from "@/lib/queries";
import { Dropdown } from "@/components/cr/dropdown";

export const LEARNING_MAX_CHARS = 1000;

/**
 * Create (no `initial`) or edit a learning. Editing cannot move a learning to another repository
 * (the API's LearningUpdate has no repo_id), so the repository picker is read-only then.
 */
export function LearningDialog({
  slug,
  repos,
  initial,
  open,
  onOpenChange,
}: {
  slug: string;
  repos: Repo[];
  initial?: Learning;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        {/* Keyed so reopening for another learning resets the form. */}
        {open ? (
          <LearningForm key={initial?.id ?? "new"} slug={slug} repos={repos} initial={initial}
            onDone={() => onOpenChange(false)} />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function LearningForm({
  slug,
  repos,
  initial,
  onDone,
}: {
  slug: string;
  repos: Repo[];
  initial?: Learning;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const uid = useId();
  const [text, setText] = useState(initial?.text ?? "");
  const [scope, setScope] = useState<LearningScope>(initial?.scope ?? "repo");
  const [repoId, setRepoId] = useState(initial?.repo_id ?? "");
  const [pathGlob, setPathGlob] = useState(initial?.path_glob ?? "");
  const [textError, setTextError] = useState<string | null>(null);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const editing = initial !== undefined;
  // An org-wide learning that never belonged to a repository cannot become repo-scoped.
  const canRepoScope = !editing || initial.repo_id !== null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    const nextTextError = trimmed ? null : "Write the preference HootPR should remember.";
    const nextRepoError = !editing && scope === "repo" && !repoId ? "Choose a repository" : null;
    setTextError(nextTextError);
    setRepoError(nextRepoError);
    if (nextTextError || nextRepoError) return;
    setSaving(true);
    const path_glob = pathGlob.trim() || null;
    try {
      if (editing) {
        await api.updateLearning(slug, initial.id, { text: trimmed, scope, path_glob });
      } else {
        await api.createLearning(slug, {
          text: trimmed,
          scope,
          repo_id: scope === "repo" ? repoId : null,
          path_glob,
        });
      }
      toast.success("Learning saved");
      await qc.invalidateQueries({ queryKey: qk.learningsAll(slug) });
      onDone();
    } catch (err) {
      if (err instanceof ApiError && (err.status === 422 || err.status === 409)) {
        if (err.code === "invalid_scope") setRepoError(err.message);
        else setTextError(err.message);
      } else {
        toast.error(err instanceof ApiError ? err.message : "Could not save the learning.");
      }
    } finally {
      setSaving(false);
    }
  };

  const ids = { text: `${uid}-text`, scope: `${uid}-scope`, repo: `${uid}-repo`, path: `${uid}-path` };
  return (
    <form className="flex flex-col gap-4" onSubmit={(e) => void submit(e)} noValidate>
      <DialogHeader>
        <DialogTitle>{editing ? "Edit learning" : "Add learning"}</DialogTitle>
        <DialogDescription>
          HootPR applies learnings to future reviews and chat answers. They never override security rules.
        </DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.text}>Learning</Label>
        <Textarea id={ids.text} value={text} maxLength={LEARNING_MAX_CHARS} rows={4}
          aria-invalid={textError ? true : undefined}
          aria-describedby={`${ids.text}-count${textError ? ` ${ids.text}-err` : ""}`}
          placeholder="We use print() for CLI output in this repository."
          onChange={(e) => {
            setText(e.target.value);
            if (textError) setTextError(null);
          }} />
        <div className="flex items-start justify-between gap-2 text-xs">
          <span id={`${ids.text}-err`} className="text-destructive">{textError}</span>
          <span id={`${ids.text}-count`} className="shrink-0 font-mono text-faint tabular-nums">
            {text.length}/{LEARNING_MAX_CHARS}
          </span>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={ids.scope}>Scope</Label>
          <Dropdown id={ids.scope} aria-label="Scope" className="w-full" value={scope}
            onChange={(e) => {
              setScope(e.target.value as LearningScope);
              setRepoError(null);
            }}>
            <option value="repo" disabled={!canRepoScope}>This repository</option>
            <option value="org">Whole organization</option>
          </Dropdown>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={ids.repo}>Repository</Label>
          <Dropdown id={ids.repo} aria-label="Learning repository" className="w-full"
            value={repoId} disabled={editing || scope !== "repo"}
            aria-invalid={repoError ? true : undefined}
            aria-describedby={repoError ? `${ids.repo}-err` : undefined}
            onChange={(e) => {
              setRepoId(e.target.value);
              setRepoError(null);
            }}>
            <option value="">{scope === "repo" ? "Select…" : "All repositories"}</option>
            {repos.map((r) => <option key={r.id} value={r.id}>{r.full_name}</option>)}
          </Dropdown>
          {repoError ? <span id={`${ids.repo}-err`} className="text-xs text-destructive">{repoError}</span> : null}
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.path}>Path glob <span className="font-normal text-muted-foreground">(optional)</span></Label>
        <Input id={ids.path} className="font-mono" value={pathGlob} placeholder="src/cli/**" maxLength={512}
          onChange={(e) => setPathGlob(e.target.value)} />
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={saving}>Cancel</Button>
        <Button type="submit" disabled={saving}>
          {saving ? <Loader2 aria-hidden className="animate-spin" /> : null}
          Save
        </Button>
      </DialogFooter>
    </form>
  );
}
