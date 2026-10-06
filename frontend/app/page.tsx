import { ChaosSection } from "@/components/cr/landing/chaos";
import { ContextSection } from "@/components/cr/landing/context";
import { CtaBand } from "@/components/cr/landing/cta";
import { FeatureSections } from "@/components/cr/landing/features";
import { LandingFooter } from "@/components/cr/landing/footer";
import { LandingHero } from "@/components/cr/landing/hero";
import { MoreWaysSection } from "@/components/cr/landing/more-ways";
import { LandingNav } from "@/components/cr/landing/nav";

export default function LandingPage() {
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
