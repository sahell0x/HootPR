"use client";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, GitMerge, Plug, ShieldCheck, Users } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/cr/page-header";
import { SettingsLayout, SettingsSection, type SettingsMode } from "@/components/cr/settings-layout";
import { GitlabBotCard } from "@/components/gitlab-bot-card";
import { MembersCard } from "@/components/members-card";
import { McpServersCard } from "@/components/mcp-servers-card";
import { QueryState } from "@/components/query-state";
import { SettingsForm, settingsGroupNav } from "@/components/settings-form";
import { Switch } from "@/components/ui/switch";
import { YamlValidator } from "@/components/yaml-validator";
import { api, ApiError } from "@/lib/api";
import type { ConfigError } from "@/lib/api-types";
import { qk, useConfigSchema, useOrg, useOrgSettings } from "@/lib/queries";
import { cn } from "@/lib/utils";

export default function OrgSettingsPage() {
  const { org: slug } = useParams<{ org: string }>();
  const qc = useQueryClient();
  const org = useOrg(slug);
  const settings = useOrgSettings(slug);
  const schema = useConfigSchema();
  const [errors, setErrors] = useState<ConfigError[]>([]);
  const [mode, setMode] = useState<SettingsMode>("concise");
  const isAdmin = org.data?.role === "admin";
  if (!org.data || !settings.data)
    return <QueryState error={org.error ?? settings.error} what="This organization" backHref="/orgs" />;
  const save = async (body: { settings: Record<string, unknown>; knowledge_base_opt_out?: boolean }) => {
    try {
      await api.putOrgSettings(slug, body);
      setErrors([]);
      toast.success("Settings saved");
      await qc.invalidateQueries({ queryKey: qk.orgSettings(slug) });
    } catch (e) {
      if (e instanceof ApiError && e.errors) setErrors(e.errors);
      toast.error(e instanceof ApiError ? e.message : "Save failed");
    }
  };
  const gitlab = org.data.provider === "gitlab";
  const yaml = mode === "yaml";
  const navGroups = yaml
    ? [{ heading: "Configuration file", items: [{ id: "validate-yaml", label: "Validate YAML", icon: ShieldCheck }] }]
    : [
        { heading: "Review configuration", items: schema.data ? settingsGroupNav(schema.data) : [] },
        { heading: "Organization", items: [
          { id: "org-knowledge-base", label: "Knowledge base", icon: BookOpen },
          ...(gitlab ? [{ id: "gitlab", label: "GitLab bot", icon: GitMerge }] : []),
          { id: "mcp-servers", label: "MCP servers", icon: Plug },
          { id: "members", label: "Members & roles", icon: Users },
        ] },
      ];
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col">
      <PageHeader
        className="mb-5"
        title="Settings"
        description="Defaults for every repository. Repository settings and .hootpr.yaml override them."
        actions={!isAdmin ? <span className="text-xs text-muted-foreground">Read-only — admins can change these</span> : null}
      />
      <SettingsLayout groups={navGroups} backHref={`/o/${slug}/repos`} mode={mode} onModeChange={setMode}>
        <section aria-labelledby="org-review-settings" className={cn("flex flex-col gap-3", yaml && "hidden")}>
          <h2 id="org-review-settings" className="sr-only">Organization review settings</h2>
          {schema.data ? (
            <SettingsForm schema={schema.data} value={settings.data.settings} readOnly={!isAdmin} errors={errors}
              expandAll={mode === "all"} onSave={(s) => save({ settings: s })} />
          ) : (
            <QueryState error={schema.error} what="The settings schema" />
          )}
        </section>
        {yaml ? (
          <div id="validate-yaml" className="scroll-mt-20">
            <YamlValidator guideHref={`/o/${slug}/config-guide`} />
          </div>
        ) : (
          <>
            <SettingsSection id="org-knowledge-base" title="Knowledge base" split
              description="Opting out disables learnings and deletes any stored learnings and embeddings.">
              <label className="flex cursor-pointer items-center justify-between gap-6">
                <span className="min-w-0">
                  <span className="block text-sm font-medium">Opt out of learnings</span>
                  <span className="mt-0.5 block text-[13px] text-muted-foreground">
                    HootPR stops remembering review feedback for this organization.
                  </span>
                </span>
                <Switch aria-label="Opt out of learnings" disabled={!isAdmin} checked={settings.data.knowledge_base_opt_out}
                  onCheckedChange={(c) => save({ settings: settings.data.settings, knowledge_base_opt_out: c })} />
              </label>
            </SettingsSection>
            {gitlab ? <GitlabBotCard slug={slug} isAdmin={isAdmin} /> : null}
            <McpServersCard slug={slug} isAdmin={isAdmin} />
            <MembersCard slug={slug} isAdmin={isAdmin} />
          </>
        )}
      </SettingsLayout>
    </div>
  );
}
