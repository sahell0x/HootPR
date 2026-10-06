// Contract C7: the form must cover the schema the backend actually publishes.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";
import { flattenSchema } from "@/lib/schema-form";

const file = path.resolve(import.meta.dirname, "../../../backend/hootpr.v1.schema.json");

test.skipIf(!existsSync(file))("every .hootpr.yaml setting has a form field with a description", () => {
  const schema = JSON.parse(readFileSync(file, "utf8"));
  const nodes = flattenSchema(schema);
  const paths = new Set(nodes.map((n) => n.path));
  for (const p of ["language", "reviews.profile", "reviews.request_changes_workflow", "reviews.path_instructions",
    "reviews.ast_grep_instructions", "reviews.tools.ast_grep.essential_rules", "reviews.tools.phpstan.level",
    "reviews.auto_review.labels", "reviews.pre_merge_checks.custom_checks", "reviews.finishing_touches.autofix.enabled",
    "chat.auto_reply", "knowledge_base.opt_out", "knowledge_base.learnings.scope",
    "knowledge_base.code_guidelines.file_patterns", "knowledge_base.linked_repositories",
    "code_generation.docstrings.path_instructions"]) expect(paths).toContain(p);
  expect(nodes.filter((n) => !n.description).map((n) => n.path)).toEqual([]);
  expect(nodes.flatMap((n) => n.item ?? []).filter((n) => !n.description).map((n) => n.path)).toEqual([]);
  expect(nodes.length).toBeGreaterThan(70);
  // Labels are unique inside a group, so every control has a distinct accessible name there.
  const seen = new Set<string>();
  for (const n of nodes) {
    const k = `${n.group}/${n.label}`;
    expect(seen.has(k), `duplicate label ${k}`).toBe(false);
    seen.add(k);
  }
});
