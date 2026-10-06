"use client";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { SettingsSection } from "@/components/cr/settings-layout";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { apiBase } from "@/lib/runtime-config";

/** `guideHref`: link to the in-app configuration guide. */
export function YamlValidator({ guideHref }: { guideHref?: string } = {}) {
  const [text, setText] = useState("");
  const validate = useMutation({ mutationFn: () => api.validateConfig(text) });
  return (
    <SettingsSection
      title="Validate .hootpr.yaml"
      description={<>Paste your file to check it against the schema (published at <code className="font-mono text-xs">{apiBase()}/schema/hootpr.v1.json</code>).
        {guideHref ? <> New to the file? <Link href={guideHref} className="text-foreground underline underline-offset-2">Read the configuration guide</Link>.</> : null}</>}
      bodyClassName="flex flex-col gap-2"
      footer={
        <>
          <div className="mr-auto min-w-0 text-sm">
            {validate.data?.valid ? (
              <p className="flex items-center gap-1.5 text-success"><CheckCircle2 aria-hidden className="size-4" />Valid configuration.</p>
            ) : null}
            {validate.data && !validate.data.valid ? (
              <p className="flex items-center gap-1.5 text-destructive">
                <XCircle aria-hidden className="size-4" />
                {validate.data.errors.length} {validate.data.errors.length === 1 ? "problem" : "problems"} found
              </p>
            ) : null}
          </div>
          <Button type="button" variant="outline" onClick={() => validate.mutate()} disabled={validate.isPending}>
            Validate
          </Button>
        </>
      }
    >
      <Label htmlFor="yaml-input" className="font-mono text-xs text-muted-foreground">.hootpr.yaml</Label>
      <Textarea id="yaml-input" rows={10} spellCheck={false} placeholder={"reviews:\n  profile: chill"}
        className="min-h-48 bg-surface font-mono text-xs leading-relaxed md:text-xs dark:bg-surface"
        value={text} onChange={(e) => setText(e.target.value)} />
      {validate.data && !validate.data.valid ? (
        <ul className="flex flex-col divide-y overflow-hidden rounded-md border border-destructive/30 bg-destructive/5 font-mono text-xs text-destructive">
          {validate.data.errors.map((e, i) => (
            <li key={i} className="px-3 py-2">{e.line ? `Line ${e.line} · ` : ""}{e.path ? `${e.path}: ` : ""}{e.message}</li>
          ))}
        </ul>
      ) : null}
    </SettingsSection>
  );
}
