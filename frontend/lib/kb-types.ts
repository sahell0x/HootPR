// Phase 7 (knowledge base) API types — aliases of the generated OpenAPI schema.
import { apiFetch } from "./api";
import type { components } from "./openapi";

type S = components["schemas"];

export type McpToolInfo = S["McpToolInfo"];

export type McpServer = S["McpServerOut"];

export type McpServerList = S["McpServerList"];

export type McpServerCreate = S["McpServerCreate"];

export type McpServerUpdate = S["McpServerUpdate"];

const base = (slug: string) => `/api/orgs/${encodeURIComponent(slug)}/mcp-servers`;

export const mcpApi = {
  list: (slug: string) => apiFetch<McpServerList>(base(slug)),
  create: (slug: string, body: McpServerCreate) =>
    apiFetch<McpServer>(base(slug), { method: "POST", body }),
  update: (slug: string, id: string, body: McpServerUpdate) =>
    apiFetch<McpServer>(`${base(slug)}/${encodeURIComponent(id)}`, { method: "PATCH", body }),
  remove: (slug: string, id: string) =>
    apiFetch<void>(`${base(slug)}/${encodeURIComponent(id)}`, { method: "DELETE" }),
  discover: (slug: string, id: string) =>
    apiFetch<McpServer>(`${base(slug)}/${encodeURIComponent(id)}/discover`, { method: "POST" }),
};

export const mcpKey = (slug: string) => ["org", slug, "mcp-servers"] as const;
