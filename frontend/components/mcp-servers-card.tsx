"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw, Server } from "lucide-react";
import { ConfirmAction } from "@/components/cr/settings-confirm";
import { SettingsSection } from "@/components/cr/settings-layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { type McpServer, mcpApi, mcpKey } from "@/lib/kb-types";

const errMsg = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

/** "Name: value" lines → header map. */
function parseHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const i = line.indexOf(":");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

function ServerRow({ slug, server, isAdmin }: { slug: string; server: McpServer; isAdmin: boolean }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: mcpKey(slug) });
  const [headers, setHeaders] = useState("");
  const update = useMutation({
    mutationFn: (body: Parameters<typeof mcpApi.update>[2]) => mcpApi.update(slug, server.id, body),
    onSuccess: refresh,
    onError: (e) => toast.error(errMsg(e, "Update failed")),
  });
  const discover = useMutation({
    mutationFn: () => mcpApi.discover(slug, server.id),
    onSuccess: (s) => {
      if (s.last_error) toast.error(s.last_error);
      else toast.success(`Found ${s.discovered_tools.length} tools`);
      return refresh();
    },
    onError: (e) => toast.error(errMsg(e, "Discovery failed")),
  });
  const remove = useMutation({
    mutationFn: () => mcpApi.remove(slug, server.id),
    onSuccess: refresh,
    onError: (e) => toast.error(errMsg(e, "Delete failed")),
  });
  const toggleTool = (name: string, on: boolean) => {
    const next = on ? [...server.allowed_tools, name] : server.allowed_tools.filter((t) => t !== name);
    update.mutate({ allowed_tools: next });
  };
  return (
    <div className="flex flex-col gap-3 border-t px-5 py-4 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span aria-hidden className={server.last_error ? "size-2 rounded-full bg-destructive" : server.enabled ? "size-2 rounded-full bg-success" : "size-2 rounded-full bg-faint"} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium">{server.name}</span>
            {server.last_error ? <Badge variant="destructive">error</Badge> : null}
          </span>
          <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{server.url}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="mr-1 flex items-center gap-2 text-[13px] text-muted-foreground">
            <Switch aria-label={`Enable ${server.name}`} checked={server.enabled} disabled={!isAdmin}
              onCheckedChange={(c) => update.mutate({ enabled: c })} />
            Enabled
          </label>
          {isAdmin ? (
            <>
              <Button size="sm" variant="outline" disabled={discover.isPending} onClick={() => discover.mutate()}>
                <RefreshCw aria-hidden className={discover.isPending ? "animate-spin" : undefined} />
                {discover.isPending ? "Connecting…" : "Discover tools"}
              </Button>
              <ConfirmAction
                trigger={<Button size="sm" variant="outline" className="text-destructive hover:text-destructive">Remove</Button>}
                title={`Remove MCP server ${server.name}?`}
                description="HootPR stops calling its tools and the stored auth headers are deleted."
                confirmLabel="Remove server" onConfirm={() => remove.mutate()} />
            </>
          ) : null}
        </div>
      </div>
      {server.last_error ? (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 font-mono text-xs text-destructive">{server.last_error}</p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Auth headers: <span className="font-mono">{server.header_names.length ? server.header_names.join(", ") : "none"}</span> (stored encrypted, never shown)
      </p>
      {server.discovered_tools.length ? (
        <div className="overflow-hidden rounded-md border">
          <p className="border-b bg-subtle px-3 py-2 text-xs font-medium text-muted-foreground">Allowed tools (only checked tools are offered to HootPR)</p>
          <div className="flex max-h-64 flex-col divide-y overflow-auto">
            {server.discovered_tools.map((t) => (
              <label key={t.name} className="flex cursor-pointer items-start gap-2.5 px-3 py-2 text-[13px] hover:bg-subtle">
                <Checkbox className="mt-0.5" disabled={!isAdmin} checked={server.allowed_tools.includes(t.name)}
                  onCheckedChange={(c) => toggleTool(t.name, c === true)} aria-label={`Allow ${t.name}`} />
                <span className="min-w-0 whitespace-normal"><span className="font-mono">{t.name}</span>
                  {t.description ? <span className="text-muted-foreground"> — {t.description}</span> : null}</span>
              </label>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No tools discovered yet. Use “Discover tools”, then allow the ones HootPR may call.</p>
      )}
      {isAdmin ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <Textarea aria-label={`Replace headers for ${server.name}`} value={headers} onChange={(e) => setHeaders(e.target.value)}
            placeholder={"Replace auth headers, one per line\nAuthorization: Bearer …"} rows={2} spellCheck={false}
            className="min-h-14 min-w-0 flex-1 bg-surface font-mono text-xs md:text-xs dark:bg-surface" />
          <Button size="sm" variant="outline" onClick={() => {
            update.mutate({ headers: parseHeaders(headers) });
            setHeaders("");
          }}>Save headers</Button>
        </div>
      ) : null}
    </div>
  );
}

export function McpServersCard({ slug, isAdmin }: { slug: string; isAdmin: boolean }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: mcpKey(slug), queryFn: () => mcpApi.list(slug) });
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [headers, setHeaders] = useState("");
  const create = useMutation({
    mutationFn: () =>
      mcpApi.create(slug, { name, url, headers: parseHeaders(headers), allowed_tools: [], enabled: true }),
    onSuccess: async (s) => {
      setName(""); setUrl(""); setHeaders("");
      toast.success(`Added ${s.name}; discovering tools…`);
      try { await mcpApi.discover(slug, s.id); } catch { /* shown on the row */ }
      await qc.invalidateQueries({ queryKey: mcpKey(slug) });
    },
    onError: (e) => toast.error(errMsg(e, "Could not add the server")),
  });
  const servers = list.data?.servers ?? [];
  const full = list.data ? servers.length >= list.data.max_servers : false;
  return (
    <SettingsSection id="mcp-servers" title="MCP servers"
      description={<>
        Remote MCP servers (streamable HTTP, https only) whose allowed tools HootPR may call during reviews and chat.
        Calls run from HootPR&apos;s worker; internal and private addresses are blocked. Disable per repository with
        <code className="mx-1 font-mono text-xs text-foreground">knowledge_base.mcp.usage: disabled</code>.
      </>}
      action={list.data ? <span className="font-mono text-xs text-faint">{servers.length}/{list.data.max_servers}</span> : null}
      bodyClassName="p-0">
      {list.error ? <p className="px-5 py-4 text-sm text-destructive">{errMsg(list.error, "Failed to load MCP servers")}</p> : null}
      {servers.length === 0 && list.data ? (
        <div className="m-5 flex flex-col items-center gap-1.5 rounded-md border border-dashed px-4 py-8 text-center">
          <Server aria-hidden className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No MCP servers yet.</p>
        </div>
      ) : null}
      {servers.map((s) => <ServerRow key={s.id} slug={slug} server={s} isAdmin={isAdmin} />)}
      {isAdmin ? (
        <form className="flex flex-col gap-3 border-t bg-subtle px-5 py-4"
          onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <p className="text-sm font-medium">Add a server</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input aria-label="Server name" placeholder="name (e.g. docs)" value={name} className="font-mono sm:w-44"
              onChange={(e) => setName(e.target.value.toLowerCase())} required />
            <Input aria-label="Server URL" placeholder="https://mcp.example.com/mcp" value={url} className="font-mono"
              aria-invalid={create.error ? true : undefined}
              onChange={(e) => { setUrl(e.target.value); if (create.error) create.reset(); }} required />
          </div>
          <Textarea aria-label="Auth headers" value={headers} onChange={(e) => setHeaders(e.target.value)} rows={2} spellCheck={false}
            placeholder={"Optional auth headers, one per line\nAuthorization: Bearer …"}
            className="min-h-14 bg-surface font-mono text-xs md:text-xs dark:bg-surface" />
          <div className="flex flex-wrap items-center justify-end gap-3">
            {create.error ? (
              <p role="alert" className="mr-auto min-w-0 text-xs text-destructive">{errMsg(create.error, "Could not add the server")}</p>
            ) : null}
            <Button type="submit" size="sm" disabled={create.isPending || full || !name || !url}>
              {full ? "Server limit reached" : create.isPending ? "Adding…" : "Add server"}
            </Button>
          </div>
        </form>
      ) : null}
    </SettingsSection>
  );
}
