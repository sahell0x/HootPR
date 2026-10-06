"use client";
import { ArrowRight, Download, GitBranch, Layers, ListChecks, MessageSquare, Settings2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { ConfigReference, CopyButton, InlineCode, YamlBlock } from "@/components/config-guide";
import { PageContainer, PageHeader } from "@/components/cr/page-header";
import { SettingsSection } from "@/components/cr/settings-layout";
import { QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { CONFIG_FILE, EXAMPLES, STARTER, defaultConfigYaml, schemaComment } from "@/lib/config-docs";
import { useConfigSchema } from "@/lib/queries";
import { apiBase } from "@/lib/runtime-config";

const TOC = [
  { id: "quick-start", label: "Quick start" },
  { id: "editor", label: "Editor autocomplete" },
  { id: "precedence", label: "How settings combine" },
  { id: "check", label: "Check your file" },
  { id: "examples", label: "Examples" },
  { id: "reference", label: "All settings" },
];

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span aria-hidden className="mt-px flex size-6 shrink-0 items-center justify-center rounded-full border bg-subtle font-mono text-xs text-muted-foreground">{n}</span>
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <div className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{children}</div>
      </div>
    </li>
  );
}

const LEVELS: { name: ReactNode; detail: string }[] = [
  { name: <InlineCode>{CONFIG_FILE}</InlineCode>, detail: "In the repository, on the pull request's base branch." },
  { name: "Repository settings", detail: "Repositories → a repository → Settings." },
  { name: "Organization settings", detail: "Organization Settings → Configuration." },
  { name: "HootPR defaults", detail: "Used for anything nobody set." },
];

const INHERIT = `inheritance: true   # merge with repository and organization settings
reviews:
  profile: assertive
`;

export default function ConfigGuidePage() {
  const { org: slug } = useParams<{ org: string }>();
  const schema = useConfigSchema();
  const schemaUrl = `${apiBase()}/schema/hootpr.v1.json`;
  const starter = `${schemaComment(schemaUrl)}\n${STARTER}`;

  const downloadDefaults = () => {
    if (!schema.data) return;
    const blob = new Blob([defaultConfigYaml(schema.data, schemaUrl)], { type: "text/yaml" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = CONFIG_FILE;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <PageContainer>
      <PageHeader
        title="Configuration guide"
        description={<>Configure HootPR from your repository with a <InlineCode>{CONFIG_FILE}</InlineCode> file — versioned, reviewed and shared like the rest of your code.</>}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href={`/o/${slug}/settings`}><Settings2 aria-hidden className="size-3.5" /> Open settings</Link>
          </Button>
        }
      />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_12rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <SettingsSection id="quick-start" title="Quick start"
            description={<>Everything you can change in the dashboard can also live in a <InlineCode>{CONFIG_FILE}</InlineCode> file at the root of your repository.</>}
            bodyClassName="flex flex-col gap-5">
            <ol className="flex flex-col gap-4">
              <Step n={1} title={`Create ${CONFIG_FILE} in the repository root`}>
                Next to your <InlineCode>README</InlineCode>. Start with the file below and keep only the settings you want to change — anything you leave out uses the default.
              </Step>
              <Step n={2} title="Merge it into your default branch">
                HootPR reads the file from the pull request&apos;s <strong className="font-medium text-foreground">base branch</strong>, so a PR can&apos;t switch off its own review.
                Edits made in a PR take effect after it is merged; HootPR notes this in the review.
              </Step>
              <Step n={3} title="Open or update a pull request">
                The next review uses the new settings. If the file has a mistake, HootPR points to the line in the review and falls back to your dashboard settings.
              </Step>
            </ol>
            <YamlBlock code={starter} />
          </SettingsSection>

          <SettingsSection id="editor" title="Editor autocomplete"
            description="Get suggestions, descriptions on hover and red underlines for mistakes while you type."
            bodyClassName="flex flex-col gap-3 text-[13px] leading-relaxed text-muted-foreground">
            <p>Put this line at the top of the file:</p>
            <div className="flex items-center gap-2 overflow-hidden rounded-md border bg-surface pl-3">
              <code className="min-w-0 flex-1 overflow-x-auto py-2 font-mono text-xs whitespace-nowrap text-faint">{schemaComment(schemaUrl)}</code>
              <CopyButton text={schemaComment(schemaUrl)} className="mr-1 shrink-0" />
            </div>
            <ul className="flex list-disc flex-col gap-1 pl-5">
              <li><span className="text-foreground">VS Code / Cursor:</span> install the &ldquo;YAML&rdquo; extension by Red Hat.</li>
              <li><span className="text-foreground">JetBrains IDEs:</span> works out of the box.</li>
              <li><span className="text-foreground">Neovim, Helix, Zed:</span> any setup that uses yaml-language-server.</li>
            </ul>
          </SettingsSection>

          <SettingsSection id="precedence" title="How settings combine"
            description="HootPR looks for settings in this order and uses the first place that has any."
            bodyClassName="flex flex-col gap-4">
            <ol className="overflow-hidden rounded-md border">
              {LEVELS.map((l, i) => (
                <li key={i} className="flex items-center gap-3 border-b px-3 py-2.5 last:border-b-0">
                  <span className="font-mono text-xs text-faint">{i + 1}</span>
                  <div className="min-w-0 text-[13px]">
                    <span className="font-medium">{l.name}</span>
                    <span className="text-muted-foreground"> — {l.detail}</span>
                  </div>
                  {i === 0 ? <span className="ml-auto shrink-0 text-[11px] text-primary">wins</span> : null}
                </li>
              ))}
            </ol>
            <div className="flex flex-col gap-2 text-[13px] leading-relaxed text-muted-foreground">
              <p>
                <span className="font-medium text-foreground">By default the winner replaces the others.</span> A {CONFIG_FILE} that only sets
                {" "}<InlineCode>reviews.profile</InlineCode> uses HootPR defaults for everything else — not your dashboard settings.
              </p>
              <p>
                <span className="font-medium text-foreground">Add <InlineCode>inheritance: true</InlineCode> to merge instead.</span> Objects merge,
                lists are combined, and single values from the file override the dashboard.
              </p>
            </div>
            <YamlBlock code={INHERIT} />
          </SettingsSection>

          <SettingsSection id="check" title="Check your file" bodyClassName="flex flex-col gap-3">
            <ul className="flex flex-col gap-3 text-[13px] leading-relaxed text-muted-foreground">
              <li className="flex gap-3">
                <ListChecks aria-hidden className="mt-0.5 size-4 shrink-0 text-foreground" />
                <span>
                  <span className="font-medium text-foreground">Validate before you commit.</span> In{" "}
                  <Link className="text-foreground underline underline-offset-2" href={`/o/${slug}/settings`}>Settings</Link>,
                  choose <span className="text-foreground">Change mode → YAML Editor</span> and paste your file. Problems are shown with line numbers.
                </span>
              </li>
              <li className="flex gap-3">
                <MessageSquare aria-hidden className="mt-0.5 size-4 shrink-0 text-foreground" />
                <span>
                  <span className="font-medium text-foreground">Ask in a pull request.</span> Comment <InlineCode>@hootpr configuration</InlineCode> and
                  HootPR replies with the settings it is using, each marked with where it came from.
                </span>
              </li>
              <li className="flex gap-3">
                <Layers aria-hidden className="mt-0.5 size-4 shrink-0 text-foreground" />
                <span>
                  <span className="font-medium text-foreground">Start from what you have.</span> A repository&apos;s Settings page shows its effective
                  configuration with <span className="text-foreground">Copy as {CONFIG_FILE}</span>, so you can move dashboard settings into the repository.
                </span>
              </li>
              <li className="flex gap-3">
                <GitBranch aria-hidden className="mt-0.5 size-4 shrink-0 text-foreground" />
                <span>
                  <span className="font-medium text-foreground">Unknown keys are errors.</span> A typo such as <InlineCode>review:</InlineCode> instead
                  of <InlineCode>reviews:</InlineCode> makes the file invalid, so mistakes never pass silently.
                </span>
              </li>
            </ul>
          </SettingsSection>

          <section id="examples" aria-labelledby="examples-title" className="scroll-mt-20 flex flex-col gap-3">
            <div>
              <h2 id="examples-title" className="text-[0.9375rem] font-medium tracking-tight">Examples</h2>
              <p className="mt-1 text-[13px] text-muted-foreground">Copy the parts you need into one file — keys under the same parent go together.</p>
            </div>
            <div className="grid gap-3 2xl:grid-cols-2">
              {EXAMPLES.map((e) => (
                <article key={e.id} id={`example-${e.id}`} className="flex min-w-0 flex-col gap-3 rounded-md border bg-card p-4">
                  <div>
                    <h3 className="text-sm font-medium">{e.title}</h3>
                    <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{e.summary}</p>
                  </div>
                  <YamlBlock code={e.yaml} className="mt-auto" />
                </article>
              ))}
            </div>
          </section>

          <section id="reference" aria-labelledby="reference-title" className="scroll-mt-20 flex flex-col gap-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 id="reference-title" className="text-[0.9375rem] font-medium tracking-tight">All settings</h2>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  Every key {CONFIG_FILE} accepts, with its type and default. Dots show nesting: <InlineCode>reviews.auto_review.drafts</InlineCode> is
                  {" "}<InlineCode>drafts</InlineCode> under <InlineCode>auto_review</InlineCode> under <InlineCode>reviews</InlineCode>; <InlineCode>[]</InlineCode> is
                  one item of a list.
                </p>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={downloadDefaults} disabled={!schema.data}>
                <Download aria-hidden className="size-3.5" /> Download full default file
              </Button>
            </div>
            {schema.data ? <ConfigReference schema={schema.data} /> : <QueryState error={schema.error} what="The settings reference" className="h-40" />}
          </section>
        </div>

        <aside className="hidden xl:block">
          <nav aria-label="On this page" className="sticky top-20 flex flex-col gap-1 text-[13px]">
            <p className="mb-1 text-xs text-faint">On this page</p>
            {TOC.map((t) => (
              <a key={t.id} href={`#${t.id}`} className="group flex items-center gap-1.5 rounded-md px-2 py-1 text-muted-foreground transition-colors hover:bg-subtle hover:text-foreground">
                {t.label}
                <ArrowRight aria-hidden className="size-3 opacity-0 transition-opacity group-hover:opacity-100" />
              </a>
            ))}
          </nav>
        </aside>
      </div>
    </PageContainer>
  );
}
