"use client";
import { Check, ChevronDown, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { ProviderIcon } from "@/components/cr/settings-provider-icon";
import { PROVIDER_NAME } from "@/components/provider-name";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useOrgs } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Sidebar header row (CodeRabbit-style): provider mark + org name + plan chip + chevron. Opens the org menu.
 * `collapsed` shows only the provider mark (icon rail).
 */
export function OrgSwitcher({
  current,
  provider,
  collapsed = false,
  className,
}: {
  current: string;
  provider?: string;
  collapsed?: boolean;
  className?: string;
}) {
  const router = useRouter();
  const { data } = useOrgs();
  const active = data?.orgs.find((o) => o.slug === current);
  const name = active?.name ?? current;
  const prov = active?.provider ?? provider ?? "github";
  // The API has no plan/tier on orgs yet: every org is on the free plan (credits are bought separately).
  const plan = "FREE";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          title={collapsed ? name : undefined}
          className={cn(
            "flex h-12 w-full shrink-0 items-center gap-2 border-b border-sidebar-border px-3 text-left text-sm font-medium text-sidebar-foreground transition-colors outline-none hover:bg-sidebar-accent/50 focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-inset",
            collapsed && "md:justify-center md:px-0",
            className,
          )}
        >
          <ProviderIcon provider={prov} className="size-4 shrink-0" />
          <span className={cn("min-w-0 truncate", collapsed && "md:sr-only")}>{name}</span>
          <span
            className={cn(
              "shrink-0 rounded-sm border border-sidebar-border px-1 py-px font-mono text-[10px] leading-3.5 font-medium tracking-wide text-muted-foreground",
              collapsed && "md:hidden",
            )}
          >
            {plan}
          </span>
          <ChevronDown
            className={cn("ml-auto size-3.5 shrink-0 text-muted-foreground", collapsed && "md:hidden")}
            aria-hidden
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" sideOffset={2} className="w-72 max-w-[calc(100vw-1rem)]">
        <DropdownMenuLabel className="text-xs text-muted-foreground">Organizations</DropdownMenuLabel>
        <div className="max-h-72 overflow-y-auto">
          {data?.orgs.map((o) => (
            <DropdownMenuItem key={o.slug} onSelect={() => router.push(`/o/${o.slug}/repos`)} className="gap-2.5">
              <Avatar className="size-5 rounded-sm">
                <AvatarImage src={o.avatar_url ?? undefined} alt="" />
                <AvatarFallback className="rounded-sm border border-border bg-muted font-mono text-[9px] font-medium text-muted-foreground">
                  {o.name.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <span className="min-w-0 flex-1 truncate" title={o.name}>
                {o.name}
              </span>
              <ProviderIcon provider={o.provider} className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="sr-only">{PROVIDER_NAME[o.provider]}</span>
              <Check
                className={cn("size-4 shrink-0 text-primary", o.slug !== current && "invisible")}
                aria-hidden
              />
            </DropdownMenuItem>
          ))}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/orgs")}>
          <Plus className="size-4 text-muted-foreground" aria-hidden /> Add organization
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
