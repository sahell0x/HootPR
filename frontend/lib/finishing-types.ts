// Phase 4 (finishing touches) API types, hand-written until lib/openapi.d.ts is regenerated.
export type FinishingKind =
  | "docstrings"
  | "unit_tests"
  | "autofix"
  | "simplify"
  | "fix_ci"
  | "ci_analysis"
  | "merge_conflict"
  | "custom";

export interface FinishingJob {
  id: string;
  repo_full_name: string;
  pr_number: number;
  kind: FinishingKind;
  recipe_name: string | null;
  trigger: "command" | "webhook";
  delivery: "commit" | "stacked_pr" | "comment";
  status: string;
  requested_by: string;
  head_sha: string;
  result_sha: string | null;
  result_pr_number: number | null;
  result_url: string | null;
  verification: "verified" | "failed" | "couldnt_verify" | "not_run";
  files_changed: number;
  summary: string | null;
  error: string | null;
  credits_charged: string;
  created_at: string;
  finished_at: string | null;
}

export interface FinishingJobList {
  jobs: FinishingJob[];
}
