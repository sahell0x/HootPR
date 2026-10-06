"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, GitMerge, Loader2, MessageSquarePlus, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { toastError } from "@/components/phase8/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { p8 } from "@/lib/phase8-api";
import type { CsReviewComment, CsWorkspace, MergeMethod, ReviewEvent } from "@/lib/phase8-types";
import { Dropdown } from "@/components/cr/dropdown";

export function CommentComposer({
  path,
  line,
  onAdd,
}: {
  path: string | null;
  line: number | null;
  onAdd: (c: CsReviewComment) => void;
}) {
  const [body, setBody] = useState("");
  const [ln, setLn] = useState<string>("");
  const target = Number(ln) || line;
  if (!path) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 border-t bg-subtle px-3 py-2.5">
      <Input className="h-8 w-20 font-mono text-xs" value={ln} placeholder={line ? String(line) : "line"} onChange={(e) => setLn(e.target.value)} aria-label="Line" />
      <Input className="h-8 min-w-0 flex-1 basis-48 text-[13px]" value={body} placeholder={`Comment on ${path}${target ? `:${target}` : ""}`}
        onChange={(e) => setBody(e.target.value)} aria-label="Review comment" />
      <Button size="sm" variant="outline" disabled={!body.trim() || !target}
        onClick={() => { onAdd({ path, line: Number(target), body: body.trim(), side: "RIGHT" }); setBody(""); setLn(""); }}>
        <MessageSquarePlus aria-hidden /> Add to review
      </Button>
    </div>
  );
}

export function ReviewPanel({
  slug,
  pr,
  ws,
  pending,
  onRemove,
  onDone,
}: {
  slug: string;
  pr: string;
  ws: CsWorkspace;
  pending: CsReviewComment[];
  onRemove: (i: number) => void;
  onDone: () => void;
}) {
  const [event, setEvent] = useState<ReviewEvent>("COMMENT");
  const [body, setBody] = useState("");
  const [method, setMethod] = useState<MergeMethod>("squash");
  const head = ws.pull.head_sha;
  const submit = useMutation({
    mutationFn: () => p8.submitReview(slug, pr, { event, body, head_sha: head, comments: pending }),
    onSuccess: () => { toast.success("Review submitted with your account"); setBody(""); onDone(); },
    onError: toastError("Could not submit the review."),
  });
  const qc = useQueryClient();
  const merge = useMutation({
    mutationFn: () => p8.merge(slug, pr, { method, head_sha: head }),
    onSuccess: (r) => {
      if (r.merged) toast.success(r.message);
      else toast.error(r.message);
      void qc.invalidateQueries({ queryKey: ["org", slug, "change-stack"] });
    },
    onError: toastError("Could not merge."),
  });
  const v = ws.viewer;
  return (
    <section aria-label="Your review" className="flex flex-col">
      <div className="flex flex-col gap-3 p-4 sm:p-5">
        {pending.length ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <ClipboardCheck className="size-3.5" aria-hidden />
            <span className="rounded-sm border border-primary/60 px-1.5 font-mono text-[11px] text-primary">{pending.length} pending</span>
            inline {pending.length === 1 ? "comment" : "comments"} will be sent with this review
          </p>
        ) : null}
        {v.reason ? <p className="border-l-2 border-caution/60 pl-2.5 text-xs leading-relaxed text-muted-foreground">{v.reason}</p> : null}
        {pending.length ? (
          <ul className="flex flex-col gap-1 text-xs">
            {pending.map((c, i) => (
              <li key={i} className="flex items-start justify-between gap-2 rounded-md border bg-background px-2.5 py-2">
                <span className="min-w-0 break-words">
                  <span className="font-mono text-faint" title={`${c.path}:${c.line}`}>{c.path.split("/").pop()}:{c.line}</span>
                  <span className="text-faint"> — </span>
                  {c.body}
                </span>
                <button type="button" aria-label="Remove comment" className="shrink-0 rounded-sm p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" onClick={() => onRemove(i)}><X className="size-3" /></button>
              </li>
            ))}
          </ul>
        ) : null}
        <Textarea rows={2} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Summary (optional for approvals)" aria-label="Review summary" className="min-h-20 bg-background text-[13px]" />
        <div className="flex flex-wrap items-center gap-2">
          <Dropdown value={event} onChange={(e) => setEvent(e.target.value as ReviewEvent)} aria-label="Verdict">
            <option value="COMMENT">Comment</option>
            <option value="APPROVE">Approve</option>
            <option value="REQUEST_CHANGES">Request changes</option>
          </Dropdown>
          <Button size="sm" className="ml-auto" disabled={!v.can_submit || submit.isPending} onClick={() => submit.mutate()}>
            {submit.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
            Submit as {v.username ? `@${v.username}` : "you"}
          </Button>
        </div>
      </div>
      {ws.pull.state !== "open" ? (
        <p className="flex items-center gap-2 border-t bg-subtle px-4 py-3 text-xs text-muted-foreground sm:px-5">
          <GitMerge className="size-3.5" aria-hidden />
          This pull request is {ws.pull.state}; merge controls are unavailable.
        </p>
      ) : (
      <div className="flex flex-wrap items-center gap-2 border-t bg-subtle px-4 py-3 sm:px-5">
          <Dropdown value={method} onChange={(e) => setMethod(e.target.value as MergeMethod)} aria-label="Merge method">
            <option value="squash">Squash and merge</option>
            <option value="merge">Create a merge commit</option>
            <option value="rebase">Rebase and merge</option>
          </Dropdown>
          <Button size="sm" variant="outline" className="ml-auto" disabled={!v.can_merge || merge.isPending}
            onClick={() => { if (window.confirm(`Merge ${ws.pull.repo_full_name}#${ws.pull.number} with your account?`)) merge.mutate(); }}>
            {merge.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <GitMerge aria-hidden />} Merge
          </Button>
      </div>
      )}
    </section>
  );
}
