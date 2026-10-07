"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, ChevronRight, CircleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { toast } from "sonner";
import { Brand } from "@/components/brand";
import { ProviderIcon } from "@/components/cr/settings-provider-icon";
import { StatusPill } from "@/components/cr/kit";
import { OrgsErrorAlert } from "@/components/orgs-error-alert";
import { PROVIDER_NAME } from "@/components/provider-name";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, loginUrl } from "@/lib/api";
import type { OrgCandidate, OrgKind, Provider, Role } from "@/lib/api-types";
import { setAuthHint, setLastOrg } from "@/lib/auth-storage";
import { qk, useMe, useOrgCandidates } from "@/lib/queries";

const ROLE_LABEL: Record<Role, string> = { admin: "Admin", member: "Member", billing_admin: "Billing admin" };
const KIND_LABEL: Record<OrgKind, string> = { org: "Organization", group: "Group", personal: "Personal" };
const PROVIDERS: Provider[] = ["github", "gitlab"];

function CandidateRow({
  c,
  onSelect,
  selecting,
}: {
  c: OrgCandidate;
  onSelect: (c: OrgCandidate) => void;
  selecting: boolean;
}) {
  const needsInstall = c.provider === "github" && !c.installed && !!c.install_url;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2.5 px-4 py-3 transition-colors hover:bg-subtle">
      <Avatar className="size-8 rounded-md">
        <AvatarImage src={c.avatar_url ?? undefined} alt="" />
        <AvatarFallback className="rounded-md border border-border bg-muted font-mono text-[11px] text-muted-foreground">
          {c.name.slice(0, 2).toUpperCase()}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1 basis-40">
        <div className="truncate text-sm font-medium" title={c.name}>
          {c.name}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span>{KIND_LABEL[c.kind]}</span>
          {c.role ? (
            <>
              <span aria-hidden className="text-faint">·</span>
              <span>{ROLE_LABEL[c.role]}</span>
            </>
          ) : null}
          <span aria-hidden className="text-faint">·</span>
          <StatusPill tone={c.installed ? "success" : "neutral"}>{c.installed ? "Installed" : "Not installed"}</StatusPill>
        </div>
      </div>
      <div className="flex shrink-0 gap-2 max-sm:w-full max-sm:justify-end">
        {needsInstall ? (
          <a className={buttonVariants({ size: "sm" })} href={c.install_url!}>
            Install on GitHub
          </a>
        ) : null}
        {c.joined && c.slug ? (
          <Link className={buttonVariants({ variant: "outline", size: "sm" })} href={`/o/${c.slug}/repos`}>
            Open <ChevronRight aria-hidden />
          </Link>
        ) : (
          <Button size="sm" variant={needsInstall ? "outline" : "default"} disabled={selecting} onClick={() => onSelect(c)}>
            Select
          </Button>
        )}
      </div>
    </li>
  );
}

function ErrorFromParams() {
  return <OrgsErrorAlert code={useSearchParams().get("error")} />;
}

export default function OrgsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const candidates = useOrgCandidates();

  useEffect(() => {
    if (me.data) setAuthHint(true);
  }, [me.data]);

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) {
      setAuthHint(false);
      router.replace(`/login?next=${encodeURIComponent("/orgs")}`);
    } else if (candidates.error instanceof ApiError && candidates.error.code === "reauth_required") {
      router.replace("/login?error=oauth_failed");
    }
  }, [me.error, candidates.error, router]);

  const select = useMutation({
    mutationFn: (c: OrgCandidate) => api.selectOrg({ provider: c.provider, provider_org_id: c.provider_org_id }),
    onSuccess: async (org) => {
      setLastOrg(org.slug);
      await qc.invalidateQueries({ queryKey: qk.orgs });
      router.push(`/o/${org.slug}/repos`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not select this organization."),
  });

  const linked = new Set(me.data?.identities.map((i) => i.provider) ?? []);
  const loadError =
    candidates.error instanceof ApiError && candidates.error.status !== 401 ? candidates.error : null;

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-8 px-4 py-12 sm:py-16">
      <Brand className="self-center" />
      <div className="text-center">
        <h1 className="text-2xl font-medium tracking-tight">Select an organization</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Pick the account whose pull requests HootPR should review. You can switch or add more later.
        </p>
      </div>
      <Suspense fallback={null}>
        <ErrorFromParams />
      </Suspense>
      {loadError ? (
        <Alert variant="destructive" role="alert">
          <CircleAlert aria-hidden />
          <AlertDescription>{loadError.message || "Could not load your organizations. Please try again."}</AlertDescription>
        </Alert>
      ) : null}
      {loadError ? null : PROVIDERS.map((provider) => {
        const items = candidates.data?.orgs.filter((c) => c.provider === provider) ?? [];
        const isLinked = linked.has(provider);
        return (
          <section key={provider} aria-labelledby={`h-${provider}`} className="flex flex-col gap-2.5">
            <div className="flex items-center justify-between gap-3">
              <h2 id={`h-${provider}`} className="eyebrow">
                {PROVIDER_NAME[provider]}
              </h2>
              {me.data && !isLinked ? (
                <a className={buttonVariants({ variant: "outline", size: "sm" })} href={loginUrl(provider, "/orgs")}>
                  Connect {PROVIDER_NAME[provider]}
                </a>
              ) : null}
            </div>
            {candidates.isLoading && isLinked ? (
              <div aria-busy="true" className="divide-y overflow-hidden rounded-md border bg-card">
                {[0, 1].map((i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-3">
                    <Skeleton className="size-8 rounded-md" />
                    <div className="flex flex-1 flex-col gap-1.5">
                      <Skeleton className="h-4 w-40" />
                      <Skeleton className="h-3 w-28" />
                    </div>
                    <Skeleton className="h-7 w-16" />
                  </div>
                ))}
              </div>
            ) : null}
            {items.length > 0 ? (
              <ul className="divide-y overflow-hidden rounded-md border bg-card">
                {items.map((c) => (
                  <CandidateRow
                    key={`${c.provider}:${c.provider_org_id}`}
                    c={c}
                    onSelect={(x) => select.mutate(x)}
                    selecting={select.isPending}
                  />
                ))}
              </ul>
            ) : me.data && !isLinked ? (
              <div className="flex flex-col items-center gap-2 rounded-md border border-dashed px-4 py-8 text-center">
                <ProviderIcon provider={provider} className="size-5 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  Connect your {PROVIDER_NAME[provider]} account to review its{" "}
                  {provider === "github" ? "repositories" : "projects"} too.
                </p>
              </div>
            ) : candidates.data ? (
              <div className="flex flex-col items-center gap-2 rounded-md border border-dashed px-4 py-8 text-center">
                <Building2 className="size-5 text-muted-foreground" aria-hidden />
                <p className="text-sm font-medium">No {PROVIDER_NAME[provider]} accounts found.</p>
                <p className="text-xs text-muted-foreground">
                  {provider === "github"
                    ? "Install the HootPR app on an account, then come back here."
                    : "Groups you belong to on GitLab will show up here."}
                </p>
              </div>
            ) : null}
          </section>
        );
      })}
    </main>
  );
}
