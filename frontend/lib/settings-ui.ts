// Presentation rules for the schema-driven settings form: which group a setting lives in and the
// label it gets. The JSON schema (contract C7) decides *what* fields exist; this file only decides
// how they are presented.

export type GroupName =
  | "General"
  | "Reviews"
  | "Auto review"
  | "Path filters & instructions"
  | "AST-grep"
  | "Tools"
  | "Pre-merge checks"
  | "Finishing touches"
  | "Chat"
  | "Knowledge base"
  | "Code generation";

export const GROUPS: GroupName[] = [
  "General", "Reviews", "Auto review", "Path filters & instructions", "AST-grep", "Tools",
  "Pre-merge checks", "Finishing touches", "Chat", "Knowledge base", "Code generation",
];

/** Groups rendered expanded even when nothing in them is overridden. */
export const OPEN_GROUPS: GroupName[] = ["General", "Reviews", "Auto review"];

export function groupOf(path: string): GroupName {
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}.`);
  if (under("code_generation")) return "Code generation";
  if (under("knowledge_base")) return "Knowledge base";
  if (under("chat")) return "Chat";
  if (under("reviews.finishing_touches")) return "Finishing touches";
  if (under("reviews.pre_merge_checks")) return "Pre-merge checks";
  if (under("reviews.ast_grep_instructions") || under("reviews.tools.ast_grep")) return "AST-grep";
  if (under("reviews.tools")) return "Tools";
  if (under("reviews.path_filters") || under("reviews.path_instructions")) return "Path filters & instructions";
  if (under("reviews.auto_review")) return "Auto review";
  if (under("reviews")) return "Reviews";
  return "General";
}

export const LABELS: Record<string, string> = {
  language: "Language",
  tone_instructions: "Tone instructions",
  "reviews.profile": "Review profile",
  "reviews.request_changes_workflow": "Request changes workflow",
  "reviews.high_level_summary": "High-level summary",
  "reviews.poem": "Poem",
  "reviews.review_status": "Review status message",
  "reviews.commit_status": "Commit status / check",
  "reviews.collapse_walkthrough": "Collapse walkthrough",
  "reviews.auto_review.enabled": "Automatic reviews",
  "reviews.auto_review.drafts": "Review drafts",
  "reviews.auto_review.auto_incremental_review": "Incremental reviews on push",
  "reviews.auto_review.base_branches": "Base branches",
  "reviews.auto_review.labels": "Labels",
  "reviews.auto_review.ignore_title_keywords": "Ignore title keywords",
  "reviews.auto_review.ignore_usernames": "Ignore usernames",
  "reviews.path_filters": "Path filters",
  "reviews.path_instructions": "Path instructions",
  "reviews.ast_grep_instructions": "Ast-grep instructions",
  "reviews.tools.ast_grep.enabled": "AST-grep",
  "reviews.tools.ast_grep.essential_rules": "AST-grep essentials rule pack",
  "chat.auto_reply": "Chat auto reply",
};

/** Pydantic `default_factory` values the JSON schema cannot express; shown as the field's default. */
export const DEFAULT_OVERRIDES: Record<string, unknown> = {
  "reviews.auto_review.ignore_title_keywords": ["WIP", "DO NOT MERGE"],
};

const GENERIC_KEYS = new Set(["language", "path_instructions", "mode", "level", "threshold", "scope", "usage", "config_file", "requirements"]);
const ACRONYMS: Record<string, string> = { yaml: "YAML", ast: "AST", pr: "PR", prs: "PRs", ci: "CI", url: "URL", mcp: "MCP" };

/** `snake_case` → "Snake case", with known acronyms upper-cased. */
export function humanize(key: string): string {
  const words = key.split("_").filter(Boolean).map((w) => ACRONYMS[w] ?? w);
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function labelFor(path: string): string {
  const known = LABELS[path];
  if (known) return known;
  const parts = path.split(".");
  const key = parts[parts.length - 1] ?? path;
  const parent = parts[parts.length - 2];
  if (parent && key === "enabled") return humanize(parent);
  if (parent && GENERIC_KEYS.has(key)) return `${humanize(parent)} ${humanize(key).toLowerCase()}`;
  return humanize(key);
}

/** "Path instructions" → "Path instruction", "Linked repositories" → "Linked repository". */
export function singularOf(label: string): string {
  if (label.endsWith("ies")) return `${label.slice(0, -3)}y`;
  if (label.endsWith("s")) return label.slice(0, -1);
  return label;
}
