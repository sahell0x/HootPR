export type Json = Record<string, unknown>;

export function getPath(obj: Json, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, k) => (acc && typeof acc === "object" ? (acc as Json)[k] : undefined), obj);
}

export function setPath(obj: Json, path: string, value: unknown): Json {
  const [head, ...rest] = path.split(".");
  if (!head) return obj;
  if (rest.length === 0) return { ...obj, [head]: value };
  const child = (obj[head] && typeof obj[head] === "object" ? obj[head] : {}) as Json;
  return { ...obj, [head]: setPath(child, rest.join("."), value) };
}

export function unsetPath(obj: Json, path: string): Json {
  const [head, ...rest] = path.split(".");
  if (!head || !(head in obj)) return obj;
  const copy = { ...obj };
  if (rest.length === 0) {
    delete copy[head];
    return copy;
  }
  const child = unsetPath((obj[head] ?? {}) as Json, rest.join("."));
  if (Object.keys(child).length === 0) delete copy[head];
  else copy[head] = child;
  return copy;
}

export const splitList = (text: string) => text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
