import { Bot, Cpu, Gavel, ListTree, TriangleAlert, Wrench } from "lucide-react";
import { AgentSteps } from "@/components/trace/agent-steps";
import { JudgeTable } from "@/components/trace/judge-table";
import { LlmCallsTable } from "@/components/trace/llm-calls-table";
import { StageTimeline } from "@/components/trace/stage-timeline";
import { ToolRuns } from "@/components/trace/tool-runs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import type { ReviewDetail } from "@/lib/api-types";

function Section({ title, icon: Icon, meta, children }:
  { title: string; icon: React.ElementType; meta?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="flex items-center gap-2 text-[0.9375rem] font-medium">
          <Icon className="size-4 shrink-0 self-center text-muted-foreground" aria-hidden />
          {title}
        </h3>
        {meta ? <span className="font-mono text-xs text-faint">{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function TraceView({ review, slug }: { review: ReviewDetail; slug: string }) {
  const t = review.trace;
  const degraded = Object.entries(review.degraded ?? {});
  return (
    <div className="flex flex-col gap-8">
      {degraded.length ? (
        <Alert className="border-caution/30 bg-caution/5"><TriangleAlert className="text-caution" aria-hidden /><AlertDescription>
          Degraded: {degraded.map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ")}
        </AlertDescription></Alert>
      ) : null}
      <Section title="Timeline" icon={ListTree} meta={t.stages.length ? `${t.stages.length} stages` : undefined}>
        <StageTimeline stages={t.stages} />
      </Section>
      <Section title="Review tasks & agent steps" icon={Bot} meta={t.tasks.length ? `${t.tasks.length} tasks · ${t.agent_steps.length} steps` : undefined}>
        <AgentSteps tasks={t.tasks} steps={t.agent_steps} />
      </Section>
      {/* LLM calls (models / tokens / cost) are internal: the API only returns them to platform owners. */}
      {t.llm_calls.length ? (
        <Section title="LLM calls" icon={Cpu} meta={`${t.llm_calls.length} calls`}>
          <LlmCallsTable calls={t.llm_calls} tasks={t.tasks} slug={slug} reviewId={review.id} />
        </Section>
      ) : null}
      <Section title="Static analysis tools" icon={Wrench} meta={t.tool_runs.length ? `${t.tool_runs.filter((r) => r.status === "ok").length} of ${t.tool_runs.length} ran` : undefined}>
        <ToolRuns runs={t.tool_runs} />
      </Section>
      <Section title="Judge verdicts" icon={Gavel} meta={review.findings.length ? `${review.findings.length} candidates` : undefined}>
        <JudgeTable findings={review.findings} />
      </Section>
    </div>
  );
}
