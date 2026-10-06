"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, KeyRound, Loader2, Lock, PlusCircle, RefreshCw, ScrollText, SearchX, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useId, useState } from "react";
import { toast } from "sonner";
import { toastError } from "@/components/phase8/errors";
import { EmptyState, SearchField } from "@/components/cr/dash-ui";
import { FilterSelect, SectionTitle, SortableHead, StatusPill, TablePagination } from "@/components/cr/kit";
import { PageContainer, PageHeader } from "@/components/cr/page-header";
import { SectionError, TableSkeleton } from "@/components/cr/pages-skeleton";
import { fmtDateTime, sortRows, usePaged, useSort } from "@/components/cr/pages-table";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { timeAgo } from "@/lib/format";
import { exportUrl, p8, qk8, useApiKeys, useAuditLogs } from "@/lib/phase8-api";
import type { ApiKey } from "@/lib/phase8-types";
import { useOrg } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { apiBase } from "@/lib/runtime-config";
import { Dropdown } from "@/components/cr/dropdown";

const code = "rounded-sm bg-muted px-1 font-mono text-xs text-foreground";

function CreateKeyDialog({ slug, open, onOpenChange }: { slug: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const uid = useId();
  const [name, setName] = useState("");
  const [expires, setExpires] = useState<number | null>(90);
  const [secret, setSecret] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => p8.createApiKey(slug, name.trim(), expires),
    onSuccess: (k) => { setSecret(k.secret); setName(""); void qc.invalidateQueries({ queryKey: qk8.apiKeys(slug) }); },
    onError: toastError("Could not create the key."),
  });
  const close = (o: boolean) => {
    onOpenChange(o);
    if (!o) setSecret(null);
  };
  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{secret ? "API key created" : "Create API Key"}</DialogTitle>
          <DialogDescription>
            {secret ? "Copy this key now — it will not be shown again." : (
              <>Use it as <code className={code}>Authorization: Bearer hpr_…</code> against <code className={code}>{apiBase()}/api/public/v1</code>. Keys are stored hashed.</>
            )}
          </DialogDescription>
        </DialogHeader>
        {secret ? (
          <div className="flex items-center gap-2 rounded-md border border-success/40 bg-success/5 p-2">
            <code className="min-w-0 flex-1 break-all font-mono text-sm text-foreground">{secret}</code>
            <Button size="icon-sm" variant="outline" aria-label="Copy key"
              onClick={() => void navigator.clipboard.writeText(secret).then(() => toast.success("Copied"))}><Copy aria-hidden /></Button>
          </div>
        ) : (
          <form id={`${uid}-f`} className="flex flex-col gap-4"
            onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${uid}-n`}>Name</Label>
              <Input id={`${uid}-n`} placeholder="Key name, e.g. Grafana" value={name} onChange={(e) => setName(e.target.value)} aria-label="Key name" autoFocus />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${uid}-e`}>Expiration</Label>
              <Dropdown id={`${uid}-e`} className="w-full" value={expires ?? 0} onChange={(e) => setExpires(Number(e.target.value) || null)} aria-label="Expiry">
                <option value={30}>Expires in 30 days</option><option value={90}>Expires in 90 days</option>
                <option value={365}>Expires in 1 year</option><option value={0}>Never expires</option>
              </Dropdown>
            </div>
          </form>
        )}
        <DialogFooter>
          {secret ? (
            <Button onClick={() => close(false)}><Check aria-hidden /> Done</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => close(false)}>Cancel</Button>
              <Button type="submit" form={`${uid}-f`} disabled={!name.trim() || create.isPending}>
                {create.isPending ? <Loader2 aria-hidden className="animate-spin" /> : <KeyRound aria-hidden />} Create key
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type KeySort = "name" | "used" | "created";

function ApiKeys({ slug, keys, onCreate }: { slug: string; keys: ReturnType<typeof useApiKeys>; onCreate: () => void }) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const { sort, toggle, sorted } = useSort<KeySort>();
  const revoke = useMutation({
    mutationFn: (id: string) => p8.revokeApiKey(slug, id),
    onSuccess: () => { toast.success("Key revoked"); setRevoking(null); void qc.invalidateQueries({ queryKey: qk8.apiKeys(slug) }); },
    onError: toastError("Could not revoke the key."),
  });
  const all = keys.data?.keys ?? [];
  const needle = search.trim().toLowerCase();
  const matching = needle ? all.filter((k) => k.name.toLowerCase().includes(needle) || k.prefix.toLowerCase().includes(needle)) : all;
  const rows = sortRows(matching, sort, (k, s) => (s === "name" ? k.name.toLowerCase() : s === "used" ? k.last_used_at : k.created_at));
  const pg = usePaged(rows);
  const now = new Date();
  return (
    <div className="flex flex-col gap-3">
      <SearchField aria-label="Search API keys" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} />
      {keys.isPending ? <TableSkeleton cols={4} rows={3} rowHeight="h-[61px]" /> : keys.isError ? (
        <SectionError title="Could not load API keys." error={keys.error} onRetry={() => void keys.refetch()} />
      ) : all.length === 0 ? (
        <EmptyState icon={KeyRound} title="No API keys yet"
          action={<Button variant="outline" onClick={onCreate}><PlusCircle aria-hidden /> Create API Key</Button>}>
          Create a key to read HootPR data from scripts and dashboards.
        </EmptyState>
      ) : (
        <div>
          <Table>
            <TableHeader><TableRow>
              <SortableHead className="sm:w-1/2" sorted={sorted("name")} onSort={() => toggle("name")}>Name</SortableHead>
              <TableHead>Status</TableHead>
              <SortableHead sorted={sorted("used")} onSort={() => toggle("used")}>Last used</SortableHead>
              <SortableHead sorted={sorted("created")} onSort={() => toggle("created")}>Created at</SortableHead>
              <TableHead className="w-px"><span className="sr-only">Actions</span></TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {pg.pageRows.length === 0 ? (
                <TableRow><TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  <SearchX aria-hidden className="mx-auto mb-2 size-4" />No keys match “{search.trim()}”.
                </TableCell></TableRow>
              ) : pg.pageRows.map((k) => {
                const expired = k.expires_at != null && new Date(k.expires_at) < now;
                return (
                  <TableRow key={k.id} className={k.revoked_at ? "text-muted-foreground" : undefined}>
                    <TableCell className="max-w-0 min-w-48 sm:w-1/2">
                      <div className={cn("truncate font-medium", k.revoked_at && "line-through decoration-faint")} title={k.name}>{k.name}</div>
                      <div className="font-mono text-xs text-muted-foreground">{k.prefix}…</div>
                    </TableCell>
                    <TableCell>
                      {k.revoked_at ? <StatusPill>Revoked</StatusPill> : expired ? <StatusPill tone="warning">Expired</StatusPill> : <StatusPill tone="success">Active</StatusPill>}
                    </TableCell>
                    <TableCell className="whitespace-nowrap" title={k.last_used_at ? new Date(k.last_used_at).toLocaleString() : undefined}>
                      {k.last_used_at ? timeAgo(k.last_used_at) : "Never"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{fmtDateTime(k.created_at)}</TableCell>
                    <TableCell className="text-right">
                      {!k.revoked_at ? (
                        <Button variant="ghost" size="icon-sm" className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                          aria-label={`Revoke ${k.name}`} title="Revoke key" onClick={() => setRevoking(k)}>
                          <Trash2 aria-hidden />
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <TablePagination {...pg} />
        </div>
      )}
      <Dialog open={revoking !== null} onOpenChange={(o) => { if (!o) setRevoking(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke this API key?</DialogTitle>
            <DialogDescription>
              Scripts using <span className="font-mono text-foreground">{revoking?.prefix}…</span> ({revoking?.name}) stop working immediately. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevoking(null)}>Cancel</Button>
            <Button variant="destructive" disabled={revoke.isPending} onClick={() => revoking && revoke.mutate(revoking.id)}>
              {revoke.isPending ? <Loader2 aria-hidden className="animate-spin" /> : null}Revoke
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const ACTIONS = [
  { value: "", label: "All" },
  { value: "org.", label: "Organization settings" },
  { value: "repo.", label: "Repositories" },
  { value: "member.", label: "Members & roles" },
  { value: "installation.", label: "Installations" },
  { value: "api_key.", label: "API keys" },
  { value: "report.", label: "Reports" },
  { value: "change_stack.", label: "Change Stack" },
  { value: "data.", label: "Exports" },
] as const;

function AuditLog({ slug }: { slug: string }) {
  const [action, setAction] = useState("");
  const [search, setSearch] = useState("");
  const q = useAuditLogs(slug, action, true);
  const { sort, toggle, sorted } = useSort<"when" | "actor" | "action">({ key: "when", dir: "desc" });
  const all = q.data?.entries ?? [];
  const needle = search.trim().toLowerCase();
  const matching = needle
    ? all.filter((e) => `${e.actor_label} ${e.action} ${JSON.stringify(e.details)}`.toLowerCase().includes(needle))
    : all;
  const rows = sortRows(matching, sort, (e, k) => (k === "when" ? e.created_at : k === "actor" ? e.actor_label.toLowerCase() : e.action));
  const pg = usePaged(rows);
  return (
    <section className="mt-12 border-t pt-8">
      <SectionTitle className="[&_h2]:text-xl"
        action={
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            {q.dataUpdatedAt ? <span className="hidden sm:inline">Last updated {timeAgo(new Date(q.dataUpdatedAt).toISOString())}</span> : null}
            <Button variant="outline" size="sm" onClick={() => void q.refetch()} disabled={q.isFetching}>
              <RefreshCw aria-hidden className={q.isFetching ? "animate-spin" : undefined} /> Refresh
            </Button>
          </div>
        }>
        Audit log
      </SectionTitle>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SearchField aria-label="Search audit log" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <FilterSelect label="Action" value={action} onChange={setAction} options={ACTIONS} />
        <a className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-8 sm:ml-auto")} href={exportUrl(slug, "audit", "csv", 365)} download>
          <Download aria-hidden /> Export CSV
        </a>
      </div>
      {q.isPending ? <TableSkeleton cols={4} rows={5} rowHeight="h-[45px]" /> : q.isError ? (
        <SectionError title="Could not load the audit log." error={q.error} onRetry={() => void q.refetch()} />
      ) : all.length === 0 ? (
        <EmptyState icon={action ? SearchX : ScrollText} title={action ? "No matching entries" : "No audit entries yet"}
          action={action ? <Button variant="outline" size="sm" onClick={() => setAction("")}>Clear filter</Button> : null}>
          {action ? "Nothing matches this filter yet." : "Settings changes, member updates and exports will be recorded here."}
        </EmptyState>
      ) : (
        <div>
          <Table>
            <TableHeader><TableRow>
              <SortableHead sorted={sorted("when")} onSort={() => toggle("when")}>When</SortableHead>
              <SortableHead sorted={sorted("actor")} onSort={() => toggle("actor")}>Actor</SortableHead>
              <SortableHead sorted={sorted("action")} onSort={() => toggle("action")}>Action</SortableHead>
              <TableHead>Details</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {pg.pageRows.length === 0 ? (
                <TableRow><TableCell colSpan={4} className="py-8 text-center text-muted-foreground">No entries match “{search.trim()}”.</TableCell></TableRow>
              ) : pg.pageRows.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="whitespace-nowrap text-muted-foreground" title={new Date(e.created_at).toLocaleString()}>{timeAgo(e.created_at)}</TableCell>
                  <TableCell className="max-w-64 truncate whitespace-nowrap" title={e.actor_label}>{e.actor_label}</TableCell>
                  <TableCell><span className="inline-flex h-5 items-center rounded-sm border bg-subtle px-1.5 font-mono text-xs whitespace-nowrap">{e.action}</span></TableCell>
                  <TableCell className="w-full max-w-0 min-w-56">
                    <p className="truncate font-mono text-xs text-muted-foreground" title={JSON.stringify(e.details)}>{JSON.stringify(e.details)}</p>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <TablePagination {...pg} />
        </div>
      )}
    </section>
  );
}

export default function ApiAuditPage() {
  const { org: slug } = useParams<{ org: string }>();
  const org = useOrg(slug);
  const isAdmin = org.data?.role === "admin";
  const keys = useApiKeys(slug, true);
  const [creating, setCreating] = useState(false);
  return (
    <PageContainer className="flex flex-col">
      <PageHeader
        title="API Keys"
        description="Programmatic access to your organization's reviews, metrics, learnings and reports."
        actions={isAdmin ? <Button onClick={() => setCreating(true)}><PlusCircle aria-hidden /> Create API Key</Button> : null}
      />
      {org.data && !isAdmin ? (
        <EmptyState icon={Lock} title="Admins only">Only organization admins can manage API keys and view the audit log.</EmptyState>
      ) : (
        <>
          <ApiKeys slug={slug} keys={keys} onCreate={() => setCreating(true)} />
          <AuditLog slug={slug} />
          <CreateKeyDialog slug={slug} open={creating} onOpenChange={setCreating} />
        </>
      )}
    </PageContainer>
  );
}
