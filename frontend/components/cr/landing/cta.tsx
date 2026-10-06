import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { CReveal } from "@/components/cr/landing/c-reveal";
import { CONTAINER } from "@/components/cr/landing/shared";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Segments along the bottom edge: [flex-grow, colour]. */
const SEGMENTS: [number, string][] = [
  [5, "#1f3a30"],
  [2.5, "#46e1a5"],
  [19, "#35323a"],
  [23, "#1d2140"],
  [2.2, "#687ff5"],
  [19, "#3a3036"],
  [2.2, "#ff570a"],
  [3.5, "#ff8a3d"],
  [23, "#d8cfc4"],
];

export function CtaBand() {
  return (
    <section aria-labelledby="cta-title" className={cn(CONTAINER, "pb-24 md:pb-32")}>
      <CReveal>
        <div className="relative overflow-hidden rounded-md border bg-card">
          <div
            aria-hidden
            className="pointer-events-none absolute -top-24 -right-24 size-[360px] rounded-full bg-primary/[0.06] blur-3xl"
          />
          <div className="relative flex flex-col gap-8 px-6 py-10 sm:px-10 md:flex-row md:items-center md:justify-between md:px-14 md:py-16">
            <h2
              id="cta-title"
              className="text-[32px] leading-[1.1] font-medium tracking-[-0.03em] text-foreground sm:text-[44px]"
            >
              Get started with HootPR
            </h2>
            <Link
              href="/login"
              className={cn(buttonVariants({ variant: "inverse", size: "lg" }), "w-fit shrink-0 rounded-sm")}
            >
              Get started <ArrowRight />
            </Link>
          </div>
          <div aria-hidden className="relative flex h-[3px] w-full overflow-hidden">
            {SEGMENTS.map(([grow, color], i) => (
              <span key={i} style={{ flexGrow: grow, background: color }} />
            ))}
            <span className="cta-shimmer absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r from-transparent via-white/80 to-transparent mix-blend-overlay" />
          </div>
          <style>{`@keyframes cta-shimmer { from { transform: translateX(-100%); } to { transform: translateX(500%); } }
.cta-shimmer { animation: cta-shimmer 3.2s cubic-bezier(.45,0,.25,1) infinite; }
@media (prefers-reduced-motion: reduce) { .cta-shimmer { display: none; } }`}</style>
        </div>
      </CReveal>
    </section>
  );
}
