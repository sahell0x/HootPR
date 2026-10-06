"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { SettingsSection } from "@/components/cr/settings-layout";
import { SettingsSelect } from "@/components/cr/settings-select";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import type { Role } from "@/lib/api-types";
import { qk, useMembers } from "@/lib/queries";

const ROLES: Role[] = ["admin", "member", "billing_admin"];

export function MembersCard({ slug, isAdmin }: { slug: string; isAdmin: boolean }) {
  const qc = useQueryClient();
  const members = useMembers(slug);
  const update = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) => api.updateMemberRole(slug, userId, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.members(slug) }),
    onError: (e) => toast.error(e instanceof ApiError && e.code === "last_admin"
      ? "An organization needs at least one admin" : "Role update failed"),
  });
  const list = members.data?.members ?? [];
  return (
    <SettingsSection id="members" title="Members & roles"
      description="Admins change settings and buy credits; billing admins buy credits and view usage; members have read-only access."
      action={members.data ? <span className="font-mono text-xs text-faint">{list.length} {list.length === 1 ? "member" : "members"}</span> : null}
      bodyClassName="p-0 [&_[data-slot=table-container]]:rounded-none [&_[data-slot=table-container]]:border-0">
      <Table>
        <TableHeader><TableRow><TableHead className="pl-5">Name</TableHead><TableHead>Username</TableHead><TableHead className="pr-5">Role</TableHead></TableRow></TableHeader>
        <TableBody>
          {list.map((m) => (
            <TableRow key={m.user_id}>
              <TableCell className="pl-5">
                <span className="flex max-w-[16rem] min-w-0 items-center gap-2.5" title={m.display_name}>
                  <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full border bg-muted font-mono text-[10px] text-muted-foreground uppercase">
                    {m.display_name.slice(0, 2)}
                  </span>
                  <span className="min-w-0 truncate">{m.display_name}</span>
                </span>
              </TableCell>
              <TableCell className="font-mono text-[13px] text-muted-foreground">{m.username ?? "—"}</TableCell>
              <TableCell className="pr-5">
                {isAdmin ? (
                  <SettingsSelect aria-label={`Role for ${m.display_name}`} value={m.role} className="min-w-36 font-mono text-[13px]"
                    onChange={(e) => update.mutate({ userId: m.user_id, role: e.target.value as Role })}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </SettingsSelect>
                ) : <Badge variant="secondary" className="font-mono">{m.role}</Badge>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SettingsSection>
  );
}
