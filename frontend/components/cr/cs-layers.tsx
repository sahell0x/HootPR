import {
  BookOpen,
  Boxes,
  Database,
  FileCode2,
  FlaskConical,
  Layers,
  LayoutPanelTop,
  type LucideIcon,
  Network,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import type { CsFile, CsGroup } from "@/lib/phase8-types";
import { cn } from "@/lib/utils";

const ICONS: [RegExp, LucideIcon][] = [
  [/secur|auth|secret|permission/i, ShieldCheck],
  [/test|spec|qa/i, FlaskConical],
  [/data|model|schema|sql|db|migration|store/i, Database],
  [/config|build|ci|infra|deps|depend|setup/i, Settings2],
  [/doc|readme/i, BookOpen],
  [/api|route|endpoint|server|handler/i, Network],
  [/ui|component|page|view|style|frontend/i, LayoutPanelTop],
  [/core|logic|domain|service|feature/i, Boxes],
];

function groupIcon(title: string): LucideIcon {
  return ICONS.find(([re]) => re.test(title))?.[1] ?? Layers;
}

/** Left "Layers" navigation: review-plan groups as sections, changed files under each. */
export function CsLayersNav({
  groups,
  active,
  onSelect,
  bare = false,
}: {
  groups: CsGroup[];
  active: string | null;
  onSelect: (f: CsFile) => void;
  /** Frameless variant for use inside another bordered card. */
  bare?: boolean;
}) {
  const files = groups.reduce((n, g) => n + g.files.length, 0);
  return (
    <nav
      aria-label="Changed files"
      className={cn(
        "flex max-h-72 min-h-0 flex-col overflow-hidden",
        bare ? "bg-subtle lg:h-full lg:max-h-none" : "rounded-md border bg-card lg:max-h-[640px] xl:max-h-none",
      )}
    >
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b px-2">
        <span className="inline-flex h-7 items-center gap-1.5 rounded-md bg-accent px-2 text-[13px] font-medium">
          <Layers className="size-3.5" aria-hidden /> Layers
        </span>
        <span className="font-mono text-[11px] text-faint">{files} {files === 1 ? "file" : "files"}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {groups.map((g, gi) => {
          const Icon = groupIcon(g.title);
          const hasActive = g.files.some((f) => f.path === active);
          return (
            <div key={g.title + gi} className="mb-2 last:mb-0">
              <div
                className={cn("flex items-center gap-2 px-2 pt-1.5 pb-1 text-[13px]", hasActive ? "text-foreground" : "text-muted-foreground")}
                title={g.rationale}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="font-mono text-[11px] text-faint">{String(gi + 1).padStart(2, "0")}</span>
                <span className="min-w-0 flex-1 truncate font-medium">{g.title}</span>
              </div>
              <ul className="ml-[15px] border-l pl-1.5">
                {g.files.map((f) => {
                  const on = active === f.path;
                  return (
                    <li key={f.path}>
                      <button
                        type="button"
                        onClick={() => onSelect(f)}
                        aria-current={on ? "true" : undefined}
                        className={cn(
                          "relative flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-xs text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground",
                          on && "bg-accent text-foreground before:absolute before:top-1 before:bottom-1 before:-left-[7px] before:w-0.5 before:rounded-full before:bg-primary",
                        )}
                        title={f.path}
                      >
                        <FileCode2 className="size-3 shrink-0 opacity-70" aria-hidden />
                        <span className="min-w-0 flex-1 truncate font-mono">{f.path.split("/").pop()}</span>
                        <span className="font-mono text-[11px] text-success">+{f.additions}</span>
                        <span className="font-mono text-[11px] text-destructive">−{f.deletions}</span>
                        {f.findings ? (
                          <span className="rounded-sm border border-primary/35 bg-primary/10 px-1 font-mono text-[10px] leading-4 text-primary">
                            {f.findings}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
        {groups.length === 0 ? <p className="p-2 text-xs text-muted-foreground">No changed files.</p> : null}
      </div>
    </nav>
  );
}
