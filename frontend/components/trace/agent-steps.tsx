import { ArrowLeft, ArrowRight, Flag } from "lucide-react";
import { useId } from "react";
import { Chip, Tag } from "@/components/cr/review-chip";
import type { AgentStep, ReviewTask } from "@/lib/api-types";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

function Node({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span aria-hidden className={cn("relative z-10 flex size-5 shrink-0 items-center justify-center rounded-sm border bg-card text-muted-foreground [&_svg]:size-3", className)}>
      {children}
    </span>
  );
}

function Step({ s }: { s: AgentStep }) {
  if (s.kind === "final") {
    const reason = typeof s.args.stop_reason === "string" ? s.args.stop_reason : "done";
    return (
      <li className="relative flex gap-3 text-sm text-muted-foreground">
        <Node className="text-success"><Flag /></Node>
        <span className="pt-0.5">Finished — stop reason: {reason}{s.output_excerpt ? ` · ${s.output_excerpt}` : ""}</span>
      </li>
    );
  }
  const call = s.kind === "tool_call";
  return (
    <li className="relative flex gap-3 text-sm">
      <Node>{call ? <ArrowRight /> : <ArrowLeft />}</Node>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <span className="font-mono text-xs text-faint">#{s.step_no}</span>
          <span className="font-mono text-[0.8125rem]">{s.tool_name}</span>
          <span className="text-xs text-faint">{call ? "call" : "result"}</span>
          {s.duration_ms != null ? <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">{formatMs(s.duration_ms)}</span> : null}
        </div>
        {call && Object.keys(s.args).length ? (
          <pre className="overflow-x-auto rounded-md border bg-surface px-3 py-2 font-mono text-xs leading-5">{JSON.stringify(s.args, null, 2)}</pre>
        ) : null}
        {s.output_excerpt ? (
          <details className="group">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">output</summary>
            <pre className="mt-1 max-h-48 overflow-auto rounded-md border bg-surface px-3 py-2 font-mono text-xs leading-5">{s.output_excerpt}</pre>
          </details>
        ) : null}
      </div>
    </li>
  );
}

function StepList({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) return null;
  return (
    <ol className="relative flex flex-col gap-3 before:absolute before:top-2 before:bottom-2 before:left-[0.59375rem] before:w-px before:bg-border">
      {steps.map((s) => <Step key={s.id} s={s} />)}
    </ol>
  );
}

const TASK_TONE: Record<string, "success" | "danger" | "info" | "neutral"> = {
  done: "success", completed: "success", failed: "danger", running: "info",
};

function TaskBlock({ task, steps }: { task: ReviewTask; steps: AgentStep[] }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-md border bg-subtle p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-faint">T{task.ordinal + 1}</span>
        <h4 id={id} className="font-medium">Task {task.ordinal + 1}: {task.title}</h4>
        <Chip tone={TASK_TONE[task.status] ?? "neutral"} mono>{task.status}</Chip>
      </div>
      {task.focus.length ? (
        <div className="flex flex-wrap gap-1.5">{task.focus.map((f) => <Tag key={f}>{f}</Tag>)}</div>
      ) : null}
      <p className="font-mono text-xs break-all text-muted-foreground">{task.files.join(", ")}</p>
      {task.rationale ? <p className="text-sm text-muted-foreground">{task.rationale}</p> : null}
      {steps.length ? <div className="border-t pt-3"><StepList steps={steps} /></div> : null}
    </section>
  );
}

export function AgentSteps({ tasks, steps }: { tasks: ReviewTask[]; steps: AgentStep[] }) {
  if (tasks.length === 0 && steps.length === 0) return <p className="py-4 text-sm text-muted-foreground">No agent tasks recorded.</p>;
  const orphan = steps.filter((s) => !s.task_id || !tasks.some((t) => t.id === s.task_id));
  return (
    <div className="flex flex-col gap-3">
      {tasks.map((t) => <TaskBlock key={t.id} task={t} steps={steps.filter((s) => s.task_id === t.id)} />)}
      {orphan.length ? <div className="rounded-md border bg-subtle p-4"><StepList steps={orphan} /></div> : null}
    </div>
  );
}
