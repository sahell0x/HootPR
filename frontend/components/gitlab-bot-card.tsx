"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmAction } from "@/components/cr/settings-confirm";
import { SettingsSection } from "@/components/cr/settings-layout";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, ApiError } from "@/lib/api";
import { qk, useGitlabBot, useGitlabProjects } from "@/lib/queries";

export function GitlabBotCard({ slug, isAdmin }: { slug: string; isAdmin: boolean }) {
  const qc = useQueryClient();
  const bot = useGitlabBot(slug);
  const connected = bot.data?.connected === true;
  const projects = useGitlabProjects(slug, connected && isAdmin);
  const [token, setToken] = useState("");
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [wholeGroup, setWholeGroup] = useState(false);

  useEffect(() => {
    if (projects.data) {
      setSelected(projects.data.projects.filter((p) => p.selected).map((p) => p.id));
      setWholeGroup(projects.data.whole_group);
    }
  }, [projects.data]);

  const connect = useMutation({
    mutationFn: () => api.putGitlabBot(slug, { token }),
    onSuccess: async () => {
      setToken(""); setTokenError(null);
      await qc.invalidateQueries({ queryKey: qk.gitlabBot(slug) });
      await qc.invalidateQueries({ queryKey: qk.org(slug) });
    },
    onError: (e) => setTokenError(e instanceof ApiError && e.code === "invalid_token"
      ? "GitLab rejected this token. It needs the api, read_api and read_user scopes."
      : e instanceof Error ? e.message : "Could not connect"),
  });
  const disconnect = useMutation({
    mutationFn: () => api.deleteGitlabBot(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org", slug] }),
  });
  const save = useMutation({
    mutationFn: () => api.putGitlabProjects(slug, { project_ids: selected, whole_group: wholeGroup }),
    onSuccess: async (res) => {
      toast.success(`Webhooks installed on ${res.repos.length} projects`);
      await qc.invalidateQueries({ queryKey: ["org", slug] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Saving projects failed"),
  });

  return (
    <SettingsSection id="gitlab" title="GitLab bot" split
      description={<>
        Create a GitLab user for HootPR, give it Developer access to your group or projects, and paste a personal
        access token with the <code className="font-mono text-xs text-foreground">api</code>, <code className="font-mono text-xs text-foreground">read_api</code> and <code className="font-mono text-xs text-foreground">read_user</code> scopes (a group access
        token also works). Comments will appear as this bot.
      </>}
      action={connected ? <Badge variant="success"><span aria-hidden className="size-1.5 rounded-full bg-success" />Connected</Badge> : null}
      bodyClassName="flex flex-col gap-4">
      {!connected ? (
        <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); connect.mutate(); }}>
          <Label htmlFor="gl-token">Bot personal access token</Label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input id="gl-token" type="password" autoComplete="off" value={token} disabled={!isAdmin}
              placeholder="glpat-…" className="font-mono sm:max-w-md" onChange={(e) => setToken(e.target.value)} />
            <Button type="submit" disabled={!isAdmin || !token || connect.isPending}>Connect</Button>
          </div>
          {tokenError ? <p className="text-sm text-destructive">{tokenError}</p> : null}
        </form>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3 rounded-md border bg-subtle px-3 py-2.5">
            <p className="text-sm">{`Connected as @${bot.data?.bot_username ?? ""}`}</p>
            {isAdmin ? (
              <ConfirmAction
                trigger={<Button variant="outline" size="sm">Disconnect</Button>}
                title="Disconnect the GitLab bot?"
                description="HootPR removes its webhooks from all projects and stops reviewing merge requests."
                confirmLabel="Disconnect" onConfirm={() => disconnect.mutate()} />
            ) : null}
          </div>
          {isAdmin && projects.data ? (
            <div className="flex flex-col gap-3">
              <label className="flex items-center justify-between gap-6 text-sm">
                <span className="min-w-0">
                  <span className="block font-medium">Whole group</span>
                  <span className="block text-[13px] text-muted-foreground">New projects are added hourly.</span>
                </span>
                <Switch checked={wholeGroup} onCheckedChange={setWholeGroup} aria-label="Whole group" />
              </label>
              <ul className="flex max-h-72 flex-col divide-y overflow-auto rounded-md border">
                {projects.data.projects.map((p) => (
                  <li key={p.id} className="flex items-center gap-2.5 px-3 py-2 hover:bg-subtle">
                    <Checkbox id={`p-${p.id}`} aria-label={p.path_with_namespace} disabled={wholeGroup}
                      checked={wholeGroup || selected.includes(p.id)}
                      onCheckedChange={(c) => setSelected((s) => (c ? [...s, p.id] : s.filter((x) => x !== p.id)))} />
                    <label htmlFor={`p-${p.id}`} className="min-w-0 flex-1 truncate font-mono text-[13px]">{p.path_with_namespace}</label>
                  </li>
                ))}
              </ul>
              <div className="flex justify-end">
                <Button onClick={() => save.mutate()} disabled={save.isPending}>Save projects</Button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </SettingsSection>
  );
}
