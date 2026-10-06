// JSON schema (contract C7, Pydantic v2 output) → a flat list of form fields. Nested models become
// dotted paths; lists of models become `objectList` fields whose `item` describes one element.
import type { ConfigSchema } from "./api-types";
import { DEFAULT_OVERRIDES, type GroupName, groupOf, labelFor } from "./settings-ui";

export type FieldKind = "bool" | "text" | "textarea" | "number" | "select" | "list" | "objectList";

export interface FieldNode {
  path: string;
  key: string;
  label: string;
  description?: string;
  kind: FieldKind;
  options?: string[];
  default: unknown;
  group: GroupName;
  /** Child fields of one list element (paths relative to the element), for `objectList`. */
  item?: FieldNode[];
  /** Edit this (free-form object) value as YAML text. */
  yaml?: boolean;
}

export interface SchemaNode {
  $ref?: string;
  type?: string | string[];
  anyOf?: SchemaNode[];
  enum?: unknown[];
  properties?: Record<string, SchemaNode>;
  items?: SchemaNode;
  default?: unknown;
  description?: string;
  title?: string;
  [k: string]: unknown;
}

export type { ConfigSchema };

const TEXTAREA_KEYS = new Set(["tone_instructions", "instructions", "requirements"]);
/** Leaf descriptions too generic to show; the parent property's description is used instead. */
const GENERIC_DESCRIPTIONS = new Set(["Enable this feature."]);

const isNull = (n: SchemaNode) => n.type === "null";

/** Follows `$ref` (`#/$defs/X`) and strips `anyOf` null branches; the node's own keys win. */
export function resolveRef(schema: ConfigSchema, node: SchemaNode): SchemaNode {
  let out: SchemaNode = node;
  for (let guard = 0; guard < 16; guard += 1) {
    if (out.$ref) {
      const { $ref, ...own } = out;
      const target = $ref.replace(/^#\//, "").split("/").reduce<unknown>(
        (acc, k) => (acc && typeof acc === "object" ? (acc as Record<string, unknown>)[k] : undefined), schema);
      if (!target || typeof target !== "object") throw new Error(`Unresolvable $ref ${$ref}`);
      out = { ...(target as SchemaNode), ...own };
      continue;
    }
    if (out.anyOf) {
      const { anyOf, ...own } = out;
      const branches = anyOf.filter((b) => !isNull(b));
      if (branches.length !== 1) return out; // a real union: leave it for the caller to treat as text
      out = { ...branches[0], ...own };
      continue;
    }
    return out;
  }
  throw new Error("$ref nesting too deep");
}

function typeOf(n: SchemaNode): string | undefined {
  if (Array.isArray(n.type)) return n.type.find((t) => t !== "null");
  return n.type;
}

function isObjectWithProps(n: SchemaNode) {
  return (typeOf(n) === "object" || n.type === undefined) && !!n.properties && Object.keys(n.properties).length > 0;
}

function emptyDefault(kind: FieldKind): unknown {
  if (kind === "bool") return false;
  if (kind === "list" || kind === "objectList") return [];
  if (kind === "number") return null;
  return "";
}

interface Ctx {
  schema: ConfigSchema;
  /** Path prefix used for group/label lookup (the full dotted path inside the config). */
  fullPrefix: string;
  /** Path prefix stored in `FieldNode.path` (relative inside object-list items). */
  prefix: string;
  parentDefault: unknown;
  parentDescription?: string;
  /** Inside an object-list element: labels come from the element-relative path. */
  inItem?: boolean;
}

function walk(node: SchemaNode, ctx: Ctx): FieldNode[] {
  const out: FieldNode[] = [];
  for (const [key, raw] of Object.entries(node.properties ?? {})) {
    const prop = resolveRef(ctx.schema, raw);
    const path = ctx.prefix ? `${ctx.prefix}.${key}` : key;
    const full = ctx.fullPrefix ? `${ctx.fullPrefix}.${key}` : key;
    const inherited = ctx.parentDefault && typeof ctx.parentDefault === "object"
      ? (ctx.parentDefault as Record<string, unknown>)[key] : undefined;
    const ownDefault = "default" in prop ? prop.default : undefined;

    if (isObjectWithProps(prop)) {
      out.push(...walk(prop, { schema: ctx.schema, fullPrefix: full, prefix: path,
        parentDefault: inherited ?? ownDefault, parentDescription: prop.description, inItem: ctx.inItem }));
      continue;
    }

    let kind: FieldKind;
    let options: string[] | undefined;
    let item: FieldNode[] | undefined;
    let yaml: boolean | undefined;
    const t = typeOf(prop);
    if (prop.enum) {
      kind = "select";
      options = prop.enum.map(String);
    } else if (t === "boolean") kind = "bool";
    else if (t === "integer" || t === "number") kind = "number";
    else if (t === "array") {
      const items = prop.items ? resolveRef(ctx.schema, prop.items) : undefined;
      if (items && isObjectWithProps(items)) {
        kind = "objectList";
        item = walk(items, { schema: ctx.schema, fullPrefix: full, prefix: "", parentDefault: undefined,
          parentDescription: prop.description, inItem: true });
      } else kind = "list";
    } else if (t === "object") {
      kind = "textarea";
      yaml = true;
    } else kind = TEXTAREA_KEYS.has(key) ? "textarea" : "text";

    const description = prop.description && !GENERIC_DESCRIPTIONS.has(prop.description)
      ? prop.description
      : ctx.parentDescription ?? prop.description;
    const dflt = inherited !== undefined ? inherited
      : ownDefault !== undefined ? ownDefault
      : full in DEFAULT_OVERRIDES ? DEFAULT_OVERRIDES[full]
      : emptyDefault(kind);
    const field: FieldNode = { path, key, label: labelFor(ctx.inItem ? path : full), kind, default: dflt, group: groupOf(full) };
    if (description) field.description = description;
    if (options) field.options = options;
    if (item) field.item = item;
    if (yaml) field.yaml = true;
    out.push(field);
  }
  return out;
}

/** Every leaf setting of the schema, in schema property order. */
export function flattenSchema(schema: ConfigSchema): FieldNode[] {
  return walk(schema as SchemaNode, { schema, fullPrefix: "", prefix: "", parentDefault: undefined });
}
