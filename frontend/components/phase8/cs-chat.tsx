"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Lightbulb, Loader2, MessagesSquare, Paperclip, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { OwlMark } from "@/components/brand";
import { CsMarkdown } from "@/components/cr/cs-markdown";
import { toastError } from "@/components/phase8/errors";
import { Textarea } from "@/components/ui/textarea";
import { shortSha, timeAgo } from "@/lib/format";
import { p8, qk8, useCsChat } from "@/lib/phase8-api";
import { cn } from "@/lib/utils";

function Initials({ name }: { name: string }) {
  return (
    <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-full border bg-accent text-[11px] font-medium text-muted-foreground uppercase">
      {name.replace(/^@/, "").slice(0, 2)}
    </span>
  );
}

export function CsChat({
  slug,
  pr,
  path,
  line,
  headSha,
}: {
  slug: string;
  pr: string;
  path: string | null;
  line: number | null;
  headSha: string;
}) {
  const qc = useQueryClient();
  const q = useCsChat(slug, pr);
  const [text, setText] = useState("");
  const [attach, setAttach] = useState(true);
  const end = useRef<HTMLDivElement>(null);
  const ask = useMutation({
    mutationFn: () =>
      p8.ask(slug, pr, { body: text, path: attach ? path : null, line: attach ? line : null, head_sha: headSha }),
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: qk8.chat(slug, pr) });
    },
    onError: toastError("Could not send the question."),
  });
  const msgs = q.data?.messages ?? [];
  useEffect(() => {
    // Scroll only the thread, not the page (scrollIntoView would also scroll the window on mobile).
    const box = end.current?.parentElement;
    if (box) box.scrollTop = box.scrollHeight;
  }, [msgs.length]);
  const attachLabel = path ? `${path}${line ? `:${line}` : ""}` : null;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
        <MessagesSquare className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-sm font-medium">Chat about this change</span>
        {msgs.length ? <span className="ml-auto font-mono text-[11px] text-faint">{msgs.length}</span> : null}
      </div>
      {headSha ? (
        <div className="flex shrink-0 items-center gap-3 px-4 pt-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" aria-hidden />
          <span className="whitespace-nowrap">Snapshot <span className="font-mono">{shortSha(headSha)}</span></span>
          <span className="h-px flex-1 bg-border" aria-hidden />
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto py-4">
        {msgs.length === 0 ? (
          <div className="mx-4 flex flex-col items-start gap-2 rounded-lg border border-dashed p-4">
            <OwlMark className="size-5" />
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Ask HootPR about the diff, a finding, or the file you are looking at. Answers are billed by actual AI usage.
            </p>
          </div>
        ) : null}
        {msgs.map((m) => {
          const mine = m.role === "user";
          const name = mine ? m.author ?? "You" : "HootPR";
          const pending = m.status === "queued" || m.status === "running";
          const meta = (
            <span className="text-xs text-muted-foreground italic">
              {timeAgo(m.created_at)}
              {m.path ? <span className="not-italic font-mono text-faint"> · {`${m.path}${m.line ? `:${m.line}` : ""}`}</span> : null}
            </span>
          );
          if (mine) {
            return (
              <div key={m.id} className="flex flex-col gap-2 bg-subtle px-4 py-3">
                <div className="flex items-center justify-end gap-2.5">
                  <div className="flex min-w-0 flex-col items-end">
                    <span className="truncate text-sm font-medium">{name}</span>
                    {meta}
                  </div>
                  <Initials name={name} />
                </div>
                <div className={cn("text-right text-[13px] leading-relaxed break-words whitespace-pre-wrap", m.status === "failed" && "text-destructive")}>
                  {m.body}
                </div>
              </div>
            );
          }
          return (
            <div key={m.id} className="flex flex-col gap-2.5 px-4">
              <div className="flex items-center gap-2.5">
                <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/15">
                  <OwlMark className="size-5" />
                </span>
                <div className="flex min-w-0 flex-col">
                  <span className="text-sm font-medium">{name}</span>
                  {meta}
                </div>
              </div>
              <div className="rounded-lg border bg-card px-4 py-3 text-[13px] leading-relaxed">
                {pending ? (
                  <span className="inline-flex items-center gap-2 text-muted-foreground" role="status">
                    <span className="flex gap-1" aria-hidden>
                      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
                      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:150ms]" />
                      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:300ms]" />
                    </span>
                    Thinking…
                  </span>
                ) : m.status === "failed" ? (
                  <p className="border-l-2 border-destructive/60 pl-2.5 break-words whitespace-pre-wrap text-destructive">{m.body}</p>
                ) : (
                  <CsMarkdown source={m.body} />
                )}
              </div>
            </div>
          );
        })}
        <div ref={end} />
      </div>
      <form
        className="flex shrink-0 flex-col gap-2.5 border-t p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) ask.mutate();
        }}
      >
        <div className="flex items-center justify-between gap-3">
          <p className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
            <Lightbulb className="size-3.5 shrink-0" aria-hidden />
            <span>Billed by AI usage</span>
          </p>
          <label
            className={cn(
              "inline-flex h-8 min-w-0 cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring items-center gap-1.5 rounded-md border px-2.5 text-xs transition-colors",
              attach && path ? "border-primary/70 text-foreground" : "text-muted-foreground",
              !path && "cursor-not-allowed opacity-60",
            )}
            title={attachLabel ? `Attach ${attachLabel}` : "No file selected"}
          >
            <input type="checkbox" className="sr-only" checked={attach} onChange={(e) => setAttach(e.target.checked)} disabled={!path} />
            <Paperclip className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate font-mono">{attachLabel ? `Attach ${attachLabel.split("/").pop()}` : "No file selected"}</span>
          </label>
        </div>
        <div className="relative rounded-lg border border-input bg-background transition-colors focus-within:border-ring/60 focus-within:ring-2 focus-within:ring-ring/30">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            className="min-h-24 resize-none border-0 bg-transparent py-2.5 pr-12 pl-3 text-[13px] shadow-none focus-visible:ring-0 dark:bg-transparent"
            placeholder="Why is this change needed? Is this finding a false positive? (Ctrl+Enter to send)"
            aria-label="Question"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim()) ask.mutate();
            }}
          />
          <button
            type="submit"
            aria-label="Ask"
            title="Ask (Ctrl+Enter)"
            disabled={!text.trim() || ask.isPending}
            className="absolute top-2 right-2 grid size-8 place-items-center rounded-md bg-primary text-primary-foreground transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50"
          >
            {ask.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
          </button>
        </div>
      </form>
    </div>
  );
}
