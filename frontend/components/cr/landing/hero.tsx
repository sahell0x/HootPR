import { LandingProductPanel } from "@/components/cr/landing-product-panel";
import { Scramble } from "@/components/cr/landing/a-scramble";
import { CONTAINER, Eyebrow } from "@/components/cr/landing/shared";
import { ProviderButtons } from "@/components/provider-buttons";
import { SignupBonusNote } from "@/components/signup-bonus-note";
import { cn } from "@/lib/utils";

const HEADLINE = "Code reviews that never sleep.";

export function LandingHero() {
  return (
    <section aria-labelledby="hero-title" className="relative">
      {/* Soft owl-orange glow behind the headline. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-16 h-[520px] opacity-60"
        style={{
          background:
            "radial-gradient(60% 55% at 22% 30%, color-mix(in oklab, var(--primary) 9%, transparent), transparent 70%)",
        }}
      />
      <div className={cn(CONTAINER, "relative pt-16 sm:pt-24 lg:pt-32")}>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_420px] lg:items-end lg:gap-16">
          <div className="flex flex-col gap-5 sm:gap-6">
            <Eyebrow>AI pull request review</Eyebrow>
            <h1
              id="hero-title"
              aria-label={HEADLINE}
              className="text-[44px] leading-[1.02] font-medium tracking-[-0.03em] text-foreground sm:text-[60px] xl:text-[72px]"
            >
              <span aria-hidden>Code reviews</span>{" "}
              <span className="block">
                <span aria-hidden>that </span>
                <Scramble text="never sleep." />
              </span>
            </h1>
          </div>
          <div className="flex flex-col gap-6 lg:pb-2">
            <p className="text-[18px] leading-[1.45] text-foreground/90 sm:text-[20px]">
              Every pull request reviewed as it opens.
              <br className="hidden sm:block" /> <span className="text-muted-foreground">Real scanners, then AI, then a judge.</span>
            </p>
            <ProviderButtons tone="inverse" />
            {/* Reserve two lines so the bonus text arriving from /api/meta does not shift the hero. */}
            <div className="min-h-10">
              <SignupBonusNote />
            </div>
          </div>
        </div>
      </div>

      <div className="relative mt-16 pb-16 sm:mt-20 sm:pb-20">
        {/* Lighter band that starts at the panel's tab row, like a stage for the product. */}
        <div aria-hidden className="absolute inset-x-0 top-[46px] bottom-0 border-t bg-surface lg:top-14" />
        <div className={cn(CONTAINER, "relative")}>
          <LandingProductPanel />
        </div>
      </div>
    </section>
  );
}
