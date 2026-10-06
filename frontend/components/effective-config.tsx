"use client";
import { Copy, FileCode2 } from "lucide-react";
import { toast } from "sonner";
import { SettingsSection } from "@/components/cr/settings-layout";
import { QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { useEffectiveConfig } from "@/lib/queries";
import { apiBase } from "@/lib/runtime-config";

/** The configuration a review of this repository would use, with `# from …` provenance comments. */
export function EffectiveConfigPanel({ slug, repoId }: { slug: string; repoId: string }) {
  const q = useEffectiveConfig(slug, repoId);

  async function copy(yaml: string) {
    const header = `# yaml-language-server: $schema=${apiBase()}/schema/hootpr.v1.json\n`;
    try {
      await navigator.clipboard.writeText(header + yaml);
      toast.success("Copied");
    } catch {
      toast.error("Could not copy to the clipboard.");
    }
  }

  return (
    <SettingsSection
      title="Effective configuration"
      description={q.data?.yaml_file_note ?? "What HootPR applies to this repository after merging organization and repository settings."}
      action={q.data ? (
        <Button type="button" variant="outline" size="sm" onClick={() => void copy(q.data.yaml)}>
          <Copy aria-hidden className="size-3.5" /> Copy as .hootpr.yaml
        </Button>
      ) : null}
      bodyClassName="flex flex-col gap-3"
    >
      {q.data ? (
        <>
          <div className="overflow-hidden rounded-md border bg-surface">
            <div className="flex h-9 items-center gap-2 border-b bg-subtle px-3">
              <FileCode2 aria-hidden className="size-3.5 text-muted-foreground" />
              <span className="font-mono text-xs text-muted-foreground">.hootpr.yaml</span>
              <span className="ml-auto font-mono text-[11px] text-faint">effective</span>
            </div>
            <pre aria-label="Effective configuration YAML" tabIndex={0}
              className="max-h-[28rem] overflow-auto p-3 font-mono text-xs leading-relaxed outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
              {q.data.yaml}
            </pre>
          </div>
          <p className="text-xs text-muted-foreground">
            <code className="font-mono"># from repository settings</code> / <code className="font-mono"># from organization settings</code> mark where a value
            comes from; unmarked values are HootPR defaults.
          </p>
        </>
      ) : (
        <QueryState error={q.error} what="The effective configuration" className="h-40" />
      )}
    </SettingsSection>
  );
}
