// One fully-typed review detail (contract C4) shared by the review-detail, findings and trace tests.
// It type-checks only while lib/openapi.d.ts matches the backend schema.
import type { ReviewDetail } from "@/lib/api-types";

const t = "2026-09-29T10:00:00Z";
export const reviewDetail: ReviewDetail = {
  id: "rev1", repo_full_name: "acme/web", pr_number: 7, pr_title: "Add login", pr_url: "https://github.com/acme/web/pull/7",
  trigger: "auto", status: "completed", skip_reason: null, credits_charged: "100.00", findings_posted: 1,
  files_considered: 3, files_reviewed: 2, input_tokens: 5400, output_tokens: 800, cost_usd: "0.000940",
  created_at: t, finished_at: "2026-09-29T10:03:00Z", base_sha: "1111111aaaa", head_sha: "2222222bbbb",
  error: null, degraded: { tools: "failed or timed out: semgrep" },
  findings: [
    { id: "f1", path: "src/login.py", start_line: 2, end_line: 3, side: "RIGHT", severity: "critical",
      category: "security", title: "SQL injection via f-string", body: "Use a parameterized query.",
      suggestion: '    q = "select * from users where name=%s"', posted: true, status: "open", source: "llm",
      confidence: 0.95, task_id: "t1", judge_verdict: "keep", judge_reason: "verified against the query builder",
      fingerprint: "a".repeat(32), evidence: ["src/login.py:2"] },
    { id: "f2", path: "src/login.py", start_line: null, end_line: 5, side: "RIGHT", severity: "nitpick",
      category: "style", title: "Rename q", body: "`query` reads better.", suggestion: null, posted: false,
      status: "open", source: "llm", confidence: 0.7, task_id: "t1", judge_verdict: "keep", judge_reason: "valid nit",
      fingerprint: "b".repeat(32), evidence: [] },
    { id: "f3", path: "src/login.py", start_line: null, end_line: 40, side: "RIGHT", severity: "minor",
      category: "bug", title: "Far away", body: "Unrelated.", suggestion: null, posted: false, status: "open",
      source: "llm", confidence: 0.4, task_id: "t1", judge_verdict: "drop", judge_reason: "outside_changed_hunk",
      fingerprint: "c".repeat(32), evidence: [] },
  ],
  trace: {
    stages: [
      { name: "config", status: "ok", started_at: t, duration_ms: 40, detail: "source: default" },
      { name: "diff", status: "ok", started_at: t, duration_ms: 120, detail: "2 of 3 files reviewable" },
      { name: "sandbox", status: "ok", started_at: t, duration_ms: 5200, detail: "12 MB checkout, network sealed" },
      { name: "tools", status: "degraded", started_at: t, duration_ms: 30000, detail: "3 findings from 4 tools" },
      { name: "agents", status: "ok", started_at: t, duration_ms: 45000, detail: "1 tasks, 3 candidate findings" },
      { name: "judge", status: "ok", started_at: t, duration_ms: 3000, detail: "3 candidates → 1 inline, 1 additional" },
    ],
    tasks: [{ id: "t1", ordinal: 0, title: "Auth changes", rationale: "login flow", files: ["src/login.py"],
              focus: ["security"], status: "done", summary: "checked login" }],
    llm_calls: [
      { id: "c1", task_id: null, role: "cheap", model: "gpt-5-nano", provider_host: "api.openai.com",
        input_tokens: 900, cached_tokens: 0, output_tokens: 120, cost_usd: "0.000093", latency_ms: 850,
        status: "ok", error: null, structured_mode: "json_schema", created_at: t },
      { id: "c2", task_id: "t1", role: "review", model: "gpt-6-luna", provider_host: "api.openai.com",
        input_tokens: 4500, cached_tokens: 2000, output_tokens: 680, cost_usd: "0.000847", latency_ms: 2300,
        status: "error", error: "rate limited", structured_mode: null, created_at: t },
    ],
    agent_steps: [
      { id: "s1", task_id: "t1", step_no: 1, kind: "tool_call", tool_name: "shell", args: { cmd: "rg get_user" },
        output_excerpt: null, duration_ms: null, created_at: t },
      { id: "s2", task_id: "t1", step_no: 2, kind: "tool_result", tool_name: "shell", args: {},
        output_excerpt: "src/login.py:2: q = f\"...\"", duration_ms: 35, created_at: t },
      { id: "s3", task_id: "t1", step_no: 3, kind: "final", tool_name: null, args: { stop_reason: "done", steps: 1 },
        output_excerpt: "checked login", duration_ms: null, created_at: t },
    ],
    tool_runs: [
      { id: "r1", tool: "ruff", status: "ok", duration_ms: 400, findings_count: 2, stderr_excerpt: null },
      { id: "r2", tool: "semgrep", status: "timeout", duration_ms: 120000, findings_count: 0,
        stderr_excerpt: "killed after 120 s" },
    ],
  },
};
