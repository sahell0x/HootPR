"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { OwlMark } from "@/components/brand";
import { LoginView } from "@/components/login-view";
import { ApiError } from "@/lib/api";
import { getDashboardUrl, hasAuthHint, setAuthHint } from "@/lib/auth-storage";
import { safeNext } from "@/lib/navigation";
import { useMe, useOrgs } from "@/lib/queries";

function LoginFromParams() {
  const router = useRouter();
  const params = useSearchParams();
  const error = params.get("error");
  const next = params.get("next");
  const me = useMe();
  const orgs = useOrgs();
  const [hint, setHint] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setHint(hasAuthHint());
  }, []);

  useEffect(() => {
    if (error) return;
    if (me.data) {
      setAuthHint(true);
      if (orgs.data || !orgs.isLoading) {
        const target = safeNext(next) ?? getDashboardUrl(orgs.data?.orgs);
        router.replace(target);
      }
    } else if (me.error instanceof ApiError && me.error.status === 401) {
      setAuthHint(false);
      setHint(false);
    }
  }, [error, next, me.data, me.error, orgs.data, orgs.isLoading, router]);

  if (!error && mounted && (hint || me.data) && !me.error) {
    return (
      <div className="flex min-h-[calc(100svh-var(--banner-h,0px))] flex-1 items-center justify-center bg-background">
        <OwlMark className="size-10 animate-pulse text-primary" />
        <span className="sr-only">Redirecting to dashboard...</span>
      </div>
    );
  }

  return <LoginView error={error} next={next} />;
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginFromParams />
    </Suspense>
  );
}
