import { expect, test } from "vitest";
import { type FieldNode, flattenSchema, resolveRef } from "@/lib/schema-form";
import { groupOf, labelFor } from "@/lib/settings-ui";
import { configSchema } from "../fixtures/config-schema";

function index(nodes: FieldNode[]) {
  return (path: string): FieldNode => {
    const n = nodes.find((x) => x.path === path);
    if (!n) throw new Error(`no field ${path}`);
    return n;
  };
}

test("flattens leaves with kinds, groups and defaults", () => {
  const nodes = flattenSchema(configSchema);
  const by = index(nodes);
  expect(by("reviews.profile")).toMatchObject({ kind: "select", options: ["chill", "assertive"], default: "chill", group: "Reviews" });
  expect(by("reviews.poem")).toMatchObject({ kind: "bool", default: false, label: "Poem" });
  expect(by("tone_instructions").kind).toBe("textarea");
  expect(by("reviews.path_filters")).toMatchObject({ kind: "list", group: "Path filters & instructions", default: [] });
  expect(by("reviews.path_instructions").kind).toBe("objectList");
  expect(by("reviews.path_instructions").item?.map((i) => i.path)).toEqual(["path", "instructions"]);
  const rule = by("reviews.ast_grep_instructions");
  expect(rule.group).toBe("AST-grep");
  expect(rule.item?.find((i) => i.path === "rule")).toMatchObject({ kind: "textarea", yaml: true });
  expect(rule.item?.find((i) => i.path === "severity")).toMatchObject({ kind: "select", default: "warning" });
  expect(rule.item?.find((i) => i.path === "files")).toMatchObject({ kind: "list" });
  expect(rule.item?.find((i) => i.path === "language")?.label).toBe("Language");
  expect(by("reviews.tools.ast_grep.essential_rules").group).toBe("AST-grep");
  expect(by("reviews.tools.semgrep.enabled")).toMatchObject({ group: "Tools", label: "Semgrep", default: true });
  expect(by("reviews.pre_merge_checks.title.mode")).toMatchObject({ kind: "select", label: "Title mode" });
  expect(by("knowledge_base.learnings.scope").group).toBe("Knowledge base");
  expect(nodes.every((n) => n.description)).toBe(true);
});

test("nullable fields strip the null branch", () => {
  const by = index(flattenSchema(configSchema));
  expect(by("reviews.pre_merge_checks.title.requirements")).toMatchObject({ kind: "textarea", default: null });
});

test("generic 'Enable this feature.' descriptions use the parent's description", () => {
  const by = index(flattenSchema(configSchema));
  expect(by("reviews.tools.semgrep.enabled").description).toBe("Run Semgrep on changed files.");
  expect(by("reviews.auto_review.enabled").description).toBe("Automatically review pull requests.");
});

test("object defaults on a property descend to leaf defaults", () => {
  const schema = { properties: { chat: { $ref: "#/$defs/Chat", default: { auto_reply: false } } },
    $defs: { Chat: { type: "object", properties: { auto_reply: { type: "boolean", default: true, description: "d" } } } } };
  expect(flattenSchema(schema)[0]!).toMatchObject({ path: "chat.auto_reply", default: false });
});

test("well-known default factories that Pydantic omits are filled in", () => {
  const schema = { properties: { reviews: { type: "object", properties: { auto_review: { type: "object", properties: {
    ignore_title_keywords: { type: "array", items: { type: "string" }, description: "d" } } } } } } };
  expect(flattenSchema(schema)[0]!.default).toEqual(["WIP", "DO NOT MERGE"]);
});

test("resolveRef merges the referenced definition under the property's own keys", () => {
  expect(resolveRef(configSchema, { $ref: "#/$defs/Chat", description: "Mine" })).toMatchObject({ title: "Chat", description: "Mine" });
  expect(resolveRef(configSchema, { anyOf: [{ type: "string" }, { type: "null" }], default: null })).toMatchObject({ type: "string", default: null });
});

test("labels and groups", () => {
  expect(labelFor("reviews.auto_review.enabled")).toBe("Automatic reviews");
  expect(labelFor("reviews.tools.phpstan.level")).toBe("Phpstan level");
  expect(labelFor("reviews.ast_grep_instructions")).toBe("Ast-grep instructions");
  expect(labelFor("reviews.related_prs")).toBe("Related PRs");
  expect(labelFor("reviews.tools.ruff.enabled")).toBe("Ruff");
  expect(labelFor("knowledge_base.code_guidelines.file_patterns")).toBe("File patterns");
  expect(groupOf("code_generation.docstrings.language")).toBe("Code generation");
  expect(groupOf("reviews.finishing_touches.autofix.enabled")).toBe("Finishing touches");
  expect(groupOf("reviews.pre_merge_checks.custom_checks")).toBe("Pre-merge checks");
  expect(groupOf("reviews.tools.ast_grep.rule_dirs")).toBe("AST-grep");
  expect(groupOf("reviews.auto_review.labels")).toBe("Auto review");
  expect(groupOf("chat.auto_reply")).toBe("Chat");
  expect(groupOf("language")).toBe("General");
  expect(groupOf("reviews.poem")).toBe("Reviews");
});
