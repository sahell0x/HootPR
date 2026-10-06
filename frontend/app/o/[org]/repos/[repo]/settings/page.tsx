"use client";
import { useQueryClient } from "@tanstack/react-query";
import { FileCode2, GitBranch, ShieldCheck } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/cr/page-header";
import { SettingsLayout, type SettingsMode } from "@/components/cr/settings-layout";
import { StatusPill } from "@/components/cr/kit";
import { EffectiveConfigPanel } from "@/components/effective-config";
import { QueryState } from "@/components/query-state";
import { SettingsForm, settingsGroupNav } from "@/components/settings-form";
import { YamlValidator } from "@/components/yaml-validator";
import { api, ApiError } from "@/lib/api";
import type { ConfigError } from "@/lib/api-types";
import { qk, useConfigSchema, useOrg, useRepoSettings } from "@/lib/queries";
import { cn } from "@/lib/utils";

export default function RepoSettingsPage() {
  const { org: slug, repo: repoId } = useParams<{ org: string; repo: string }>();
  const qc = useQueryClient();
  const org = useOrg(slug);
  const data = useRepoSettings(slug, repoId);
  const schema = useConfigSchema();
  const [errors, setErrors] = useState<ConfigError[]>([]);
  const [mode, setMode] = useState<SettingsMode>("concise");
  if (!data.data) return <QueryState error={data.error} what="This repository" backHref={`/o/${slug}/repos`} />;
  const repo = data.data.repo;
  const yaml = mode === "yaml";
  const fileItems = [
    { id: "effective-config", label: "Effective configuration", icon: FileCode2 },
    { id: "validate-yaml", label: "Validate YAML", icon: ShieldCheck },
  ];
  const navGroups = yaml
    ? [{ heading: "Configuration file", items: fileItems }]
    : [
        { heading: "Review configuration", items: schema.data ? settingsGroupNav(schema.data) : [] },
        { heading: "Configuration file", items: fileItems },
      ];
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col">
      <PageHeader
        className="mb-3"
        title={<span className="min-w-0 font-mono text-xl tracking-tight break-all">{repo.full_name}</span>}
        description={
          <>
            Repository settings override organization settings. A <code className="font-mono text-xs text-foreground">.hootpr.yaml</code> on
            the default branch overrides both (set <code className="font-mono text-xs text-foreground">inheritance: true</code> in it to merge instead).
          </>
        }
      />
      <div className="mb-5 flex min-w-0 flex-wrap items-center gap-2">
        <span title={repo.default_branch}
          className="inline-flex h-5 max-w-full min-w-0 items-center gap-1 rounded-sm border px-1.5 font-mono text-xs text-muted-foreground">
          <GitBranch aria-hidden className="size-3 shrink-0" /><span className="truncate">{repo.default_branch}</span>
        </span>
        <span className="inline-flex h-5 items-center rounded-sm border px-1.5 text-xs text-muted-foreground">
          {repo.private ? "Private" : "Public"}
        </span>
        <StatusPill tone={repo.enabled ? "success" : "neutral"}>{repo.enabled ? "Reviews on" : "Reviews off"}</StatusPill>
        {org.data && org.data.role !== "admin" ? (
          <span className="text-xs text-muted-foreground">Read-only — admins can change these</span>
        ) : null}
      </div>
      <SettingsLayout groups={navGroups} backHref={`/o/${slug}/repos`} mode={mode} onModeChange={setMode}>
        <div className={cn(yaml && "hidden")}>
          {schema.data ? (
            <SettingsForm schema={schema.data} value={data.data.settings} readOnly={org.data?.role !== "admin"} errors={errors}
              expandAll={mode === "all"}
              onSave={async (settings) => {
                try {
                  await api.putRepoSettings(slug, repoId, { settings });
                  setErrors([]);
                  toast.success("Settings saved");
                  await Promise.all([
                    qc.invalidateQueries({ queryKey: qk.repoSettings(slug, repoId) }),
                    qc.invalidateQueries({ queryKey: qk.effectiveConfig(slug, repoId) }),
                  ]);
                } catch (e) {
                  if (e instanceof ApiError && e.errors) setErrors(e.errors);
                  toast.error(e instanceof ApiError ? e.message : "Save failed");
                }
              }} />
          ) : (
            <QueryState error={schema.error} what="The settings schema" />
          )}
        </div>
        <div id="effective-config" className="scroll-mt-20">
          <EffectiveConfigPanel slug={slug} repoId={repoId} />
        </div>
        <div id="validate-yaml" className="scroll-mt-20">
          <YamlValidator guideHref={`/o/${slug}/config-guide`} />
        </div>
      </SettingsLayout>
    </div>
  );
}
