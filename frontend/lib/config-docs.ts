// `.hootpr.yaml` guide content: the field reference is derived from the published JSON schema, so it
// never drifts from what the validator accepts; the examples below are checked against the schema in
// tests/unit/config-docs.test.ts.
import { stringify } from "yaml";
import type { ConfigSchema } from "./api-types";
import { resolveRef, type SchemaNode } from "./schema-form";

export const CONFIG_FILE = ".hootpr.yaml";

export interface RefField {
  /** Dotted path; list elements use `[]` (`reviews.path_instructions[].path`). */
  path: string;
  key: string;
  type: string;
  description?: string;
  default?: unknown;
  options?: string[];
  min?: number;
  max?: number;
}

export interface RefGroup {
  /** Dotted path of the object these fields belong to ("" for the top level). */
  path: string;
  description?: string;
  fields: RefField[];
}

function typeOf(n: SchemaNode): string | undefined {
  return Array.isArray(n.type) ? n.type.find((t) => t !== "null") : n.type;
}

const hasProps = (n: SchemaNode) => !!n.properties && Object.keys(n.properties).length > 0;

function typeLabel(schema: ConfigSchema, n: SchemaNode): string {
  if (n.enum) return "enum";
  const t = typeOf(n);
  if (t === "array") {
    const items = n.items ? resolveRef(schema, n.items) : undefined;
    if (items && hasProps(items)) return "list of objects";
    return `list of ${items ? typeLabel(schema, items) : "values"}s`;
  }
  if (t === "integer") return "number";
  if (t === "object") return "object";
  return t ?? "value";
}

/**
 * Every object of the schema as a group of its scalar/list fields, in schema order. Nested objects
 * become their own group; list-of-object elements get a `[]` group after their list field.
 */
export function referenceGroups(schema: ConfigSchema): RefGroup[] {
  const groups: RefGroup[] = [];
  const visit = (node: SchemaNode, path: string, description?: string) => {
    const group: RefGroup = { path, description, fields: [] };
    groups.push(group);
    const nested: [SchemaNode, string, string | undefined][] = [];
    for (const [key, raw] of Object.entries(node.properties ?? {})) {
      const prop = resolveRef(schema, raw);
      const full = path ? `${path}.${key}` : key;
      if (hasProps(prop) && typeOf(prop) !== "array") {
        nested.push([prop, full, prop.description]);
        continue;
      }
      const field: RefField = { path: full, key, type: typeLabel(schema, prop) };
      if (prop.description) field.description = prop.description;
      if ("default" in prop) field.default = prop.default;
      if (prop.enum) field.options = prop.enum.map(String);
      if (typeof prop.minimum === "number") field.min = prop.minimum;
      if (typeof prop.maximum === "number") field.max = prop.maximum;
      group.fields.push(field);
      if (typeOf(prop) === "array" && prop.items) {
        const items = resolveRef(schema, prop.items);
        if (hasProps(items)) nested.push([items, `${full}[]`, `One entry of ${key}.`]);
      }
    }
    for (const [n, p, d] of nested) visit(n, p, d);
  };
  visit(schema as SchemaNode, "", "Top-level settings.");
  return groups.filter((g) => g.fields.length > 0);
}

/** The full default configuration, built from the schema defaults (objects recurse). */
export function defaultConfig(schema: ConfigSchema): Record<string, unknown> {
  const build = (node: SchemaNode): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(node.properties ?? {})) {
      const prop = resolveRef(schema, raw);
      if (hasProps(prop) && typeOf(prop) !== "array") out[key] = build(prop);
      else if ("default" in prop) out[key] = prop.default;
    }
    return out;
  };
  return build(schema as SchemaNode);
}

export function schemaComment(schemaUrl: string) {
  return `# yaml-language-server: $schema=${schemaUrl}`;
}

export function defaultConfigYaml(schema: ConfigSchema, schemaUrl: string) {
  return `${schemaComment(schemaUrl)}\n${stringify(defaultConfig(schema), { lineWidth: 0 })}`;
}

/** A value rendered the way it would be written in the YAML file. */
export function yamlValue(v: unknown): string {
  if (v === undefined) return "";
  if (typeof v === "string") return v === "" ? '""' : /^[\w@ .\-/!]+$/.test(v) && v.trim() === v ? v : JSON.stringify(v);
  return stringify(v, { flow: true, lineWidth: 0 }).trim();
}

export const STARTER = `language: en-US
reviews:
  profile: chill            # chill = fewer, high-signal comments; assertive = also nitpicks
  auto_review:
    enabled: true
    drafts: false
  path_filters:
    - "!**/*.lock"
    - "!dist/**"
chat:
  auto_reply: true
`;

export interface ConfigExample {
  id: string;
  title: string;
  summary: string;
  yaml: string;
}

export const EXAMPLES: ConfigExample[] = [
  {
    id: "paths",
    title: "Skip files and give per-folder instructions",
    summary: "path_filters decides which files are reviewed (prefix ! to exclude). path_instructions adds guidance for files matching a glob.",
    yaml: `reviews:
  path_filters:
    - "!**/generated/**"
    - "!**/*.snap"
  path_instructions:
    - path: "src/api/**"
      instructions: |
        Check every handler validates its input and returns typed errors.
    - path: "**/*.test.ts"
      instructions: Focus on missing edge cases, not style.
`,
  },
  {
    id: "auto-review",
    title: "Control when reviews run",
    summary: "Review extra base branches, only labelled PRs, or skip bots and WIP titles. Comment @hootpr review to review a skipped PR by hand.",
    yaml: `reviews:
  auto_review:
    enabled: true
    drafts: false
    base_branches:
      - "release/.*"
    labels:
      - "!no-review"
    ignore_title_keywords:
      - WIP
      - DO NOT MERGE
    ignore_usernames:
      - dependabot[bot]
`,
  },
  {
    id: "tone",
    title: "Language, tone and review style",
    summary: "Write comments in another language, set a tone, and pick how strict reviews are.",
    yaml: `language: de-DE
tone_instructions: Be concise and friendly. Suggest, don't command.
reviews:
  profile: assertive
  poem: false
  collapse_walkthrough: true
  request_changes_workflow: true
`,
  },
  {
    id: "checks",
    title: "Pre-merge checks",
    summary: "Built-in checks for title, description, docstrings and linked issues, plus your own checks in plain English. error fails the check; warning only reports it.",
    yaml: `reviews:
  pre_merge_checks:
    title:
      mode: error
      requirements: "Use Conventional Commits, e.g. feat(api): add search"
    docstrings:
      mode: warning
      threshold: 70
    custom_checks:
      - name: Migrations are reversible
        mode: error
        instructions: Every new database migration has a working down() step.
`,
  },
  {
    id: "tools",
    title: "Turn analysis tools on or off",
    summary: "All linters and scanners are on by default and only run on files they understand. Switch off the ones you don't want.",
    yaml: `reviews:
  tools:
    eslint:
      enabled: false
    semgrep:
      enabled: true
      config_file: .semgrep.yml
    phpstan:
      level: 7
`,
  },
  {
    id: "recipes",
    title: "Custom finishing touches",
    summary: "Name a change HootPR can make on request; run it in a PR with @hootpr run <name>.",
    yaml: `reviews:
  finishing_touches:
    unit_tests:
      enabled: true
    custom:
      - name: add-logging
        instructions: Add structured debug logging to every new public function.
`,
  },
  {
    id: "knowledge",
    title: "Knowledge base and context",
    summary: "Decide where learnings apply, add your own guideline files, and pull in related repositories.",
    yaml: `knowledge_base:
  learnings:
    scope: global
  code_guidelines:
    file_patterns:
      - "docs/conventions/**/*.md"
  linked_repositories:
    - repository: acme/shared-types
      instructions: API types used by this service live here.
`,
  },
  {
    id: "ast-grep",
    title: "Syntax-aware rules (ast-grep)",
    summary: "Match code by structure and attach an instruction the reviewer applies to every match.",
    yaml: `reviews:
  ast_grep_instructions:
    - id: no-console-log
      language: typescript
      message: Use the shared logger instead of console.log.
      severity: warning
      rule:
        pattern: console.log($$$ARGS)
`,
  },
];
