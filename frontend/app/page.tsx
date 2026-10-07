"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { OwlMark } from "@/components/brand";
import { ChaosSection } from "@/components/cr/landing/chaos";
import { ContextSection } from "@/components/cr/landing/context";
import { CtaBand } from "@/components/cr/landing/cta";
import { FeatureSections } from "@/components/cr/landing/features";
import { LandingFooter } from "@/components/cr/landing/footer";
import { LandingHero } from "@/components/cr/landing/hero";
import { MoreWaysSection } from "@/components/cr/landing/more-ways";
import { LandingNav } from "@/components/cr/landing/nav";
import { ApiError } from "@/lib/api";
import { getDashboardUrl, hasAuthHint, setAuthHint } from "@/lib/auth-storage";
import { useMe, useOrgs } from "@/lib/queries";

export default function LandingPage() {
  const router = useRouter();
  const me = useMe();
  const orgs = useOrgs();
  const [hint, setHint] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setHint(hasAuthHint());
  }, []);

  useEffect(() => {
    if (me.data) {
      setAuthHint(true);
      if (orgs.data || !orgs.isLoading) {
        router.replace(getDashboardUrl(orgs.data?.orgs));
      }
    } else if (me.error instanceof ApiError && me.error.status === 401) {
      setAuthHint(false);
      setHint(false);
    }
  }, [me.data, me.error, orgs.data, orgs.isLoading, router]);

  // If already logged in, do not flash the landing page
  if (mounted && (hint || me.data) && !me.error) {
    return (
      <div
        className="flex min-h-screen flex-col items-center justify-center bg-background"
        aria-label="Loading dashboard"
      >
        <OwlMark className="size-10 animate-pulse text-primary" />
        <span className="sr-only">Redirecting to dashboard...</span>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <LandingNav />
      <main className="flex flex-col">
        <LandingHero />
        <ChaosSection />
        <FeatureSections />
        <ContextSection />
        <MoreWaysSection />
        <CtaBand />
      </main>
      <LandingFooter />
    </div>
  );
}
