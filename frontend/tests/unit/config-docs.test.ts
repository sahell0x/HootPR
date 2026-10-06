// The configuration guide must teach only keys the backend accepts and list every key it accepts.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { parse } from "yaml";
import { expect, test } from "vitest";
import { defaultConfig, EXAMPLES, referenceGroups, STARTER, yamlValue } from "@/lib/config-docs";
import { flattenSchema, resolveRef, type SchemaNode } from "@/lib/schema-form";

const file = path.resolve(import.meta.dirname, "../../../backend/hootpr.v1.schema.json");
const load = () => JSON.parse(readFileSync(file, "utf8"));

/** Dotted key paths of a parsed YAML document; list items of objects use `[]`. */
function keyPaths(v: unknown, prefix = ""): string[] {
  if (Array.isArray(v)) return v.flatMap((i) => (i && typeof i === "object" ? keyPaths(i, `${prefix}[]`) : []));
  if (!v || typeof v !== "object") return [];
  return Object.entries(v).flatMap(([k, c]) => {
    const p = prefix ? `${prefix}.${k}` : k;
    return [p, ...keyPaths(c, p)];
  });
}

function schemaHas(schema: SchemaNode, p: string): boolean {
  let node: SchemaNode = schema;
  for (const part of p.replace(/\[\]/g, ".[]").split(".").filter(Boolean)) {
    node = resolveRef(schema, node);
    if (part === "[]") {
      if (!node.items) return false;
      node = node.items;
      continue;
    }
    // Free-form objects (ast-grep `rule`) accept any key below them.
    if (!node.properties && node.type === "object") return true;
    const next = node.properties?.[part];
    if (!next) return false;
    node = next;
  }
  return true;
}

test.skipIf(!existsSync(file))("every example key exists in the published schema", () => {
  const schema = load();
  for (const doc of [STARTER, ...EXAMPLES.map((e) => e.yaml)]) {
    const bad = keyPaths(parse(doc)).filter((p) => !schemaHas(schema, p));
    expect(bad).toEqual([]);
  }
});

test.skipIf(!existsSync(file))("the reference lists every setting the form knows", () => {
  const schema = load();
  const listed = new Set(referenceGroups(schema).flatMap((g) => g.fields.map((f) => f.path)));
  const missing = flattenSchema(schema).map((n) => n.path).filter((p) => !listed.has(p));
  expect(missing).toEqual([]);
  expect(listed).toContain("reviews.path_instructions[].path");
  const d = defaultConfig(schema) as { reviews: { profile: string; auto_review: { enabled: boolean } } };
  expect(d.reviews.profile).toBe("chill");
  expect(d.reviews.auto_review.enabled).toBe(true);
});

test("yamlValue renders values as they are written in YAML", () => {
  expect(yamlValue("chill")).toBe("chill");
  expect(yamlValue("")).toBe('""');
  expect(yamlValue(true)).toBe("true");
  expect(yamlValue(["WIP", "DO NOT MERGE"])).toBe("[ WIP, DO NOT MERGE ]");
});
