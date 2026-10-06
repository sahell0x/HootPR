import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Landing content width, measured from coderabbit.ai: full-bleed up to 1920px with 24px gutters,
 * 48px from 1280px and 120px from 1440px — content sits close to the screen edges on wide displays.
 */
export const CONTAINER = "mx-auto w-full max-w-[1920px] px-6 xl:max-[1439.98px]:px-12 min-[1440px]:px-[120px]";

/** Mono uppercase mint eyebrow: "01 REVIEW", "AI PULL REQUEST REVIEW". */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("font-mono text-[12px] tracking-[0.02em] text-success uppercase", className)}>{children}</p>;
}
