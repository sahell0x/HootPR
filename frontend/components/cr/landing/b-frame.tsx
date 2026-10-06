"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";
import { CONTAINER, Eyebrow } from "./shared";

export type FeatureItem = { title: string; body: string; dotted?: boolean };

/** Segment colours for the progress bar, like the reference: mint, violet, orange, white, amber. */
const SEG = ["#46e1a5", "#8b7cf6", "#ff6a1f", "#efedf0", "#ffc53d"];
const SLIDE_MS = 4000;

/** Keyframes shared by every B-mock (fade/slide per slide change, progress fill, pulses). */
const CSS = `
@keyframes b-fill{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes b-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes b-pop{from{opacity:0;transform:translateY(6px) scale(.97)}to{opacity:1;transform:none}}
@keyframes b-type{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
@keyframes b-pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes b-draw{from{stroke-dashoffset:var(--b-len,600)}to{stroke-dashoffset:0}}
.b-in{animation:b-in .5s cubic-bezier(.2,.7,.2,1) both}
.b-pop{animation:b-pop .45s cubic-bezier(.2,.7,.2,1) both}
.b-type{animation:b-type .9s steps(40,end) both}
.b-pulse{animation:b-pulse 1.6s ease-in-out infinite}
.b-draw{stroke-dasharray:var(--b-len,600);animation:b-draw 1.4s cubic-bezier(.3,.6,.2,1) both}
@keyframes b-grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes b-wipe{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
@keyframes b-glow{0%{background:rgba(255,138,61,.28)}100%{background:transparent}}
.b-grow{transform-origin:left;animation:b-grow .9s cubic-bezier(.3,.7,.2,1) both}
.b-wipe{animation:b-wipe 1.6s cubic-bezier(.4,.6,.2,1) both}
.b-glow{animation:b-glow 1.6s ease-out both}
`;

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return reduced;
}

export function FeatureBlock({
  id,
  eyebrow,
  title,
  intro,
  items,
  cta,
  mock,
}: {
  id: string;
  eyebrow: string;
  title: string;
  intro: string;
  items: FeatureItem[];
  cta: { label: string; href: string };
  mock: (active: number) => ReactNode;
}) {
  const [active, setActive] = useState(0);
  const [inView, setInView] = useState(false);
  const [seen, setSeen] = useState(false);
  const reduced = useReducedMotion();
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        const hit = e?.isIntersecting ?? false;
        setInView(hit);
        if (hit) setSeen(true);
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const next = useCallback(
    () => setActive((a) => (a + 1) % items.length),
    [items.length],
  );
  // Keeps advancing while the cursor is over it; only pauses off-screen or with reduced motion.
  const running = inView && !reduced;

  return (
    <section
      id={id}
      ref={ref}
      className="scroll-mt-24 py-16 md:py-20"
      aria-labelledby={`${id}-title`}
    >
      <style>{CSS}</style>
      <div className={CONTAINER}>
        <div
          className={cn(
            "transition-[opacity,transform] duration-700 ease-out",
            seen ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0",
          )}
        >
          <Eyebrow>{eyebrow}</Eyebrow>
          <h3
            id={`${id}-title`}
            className="mt-5 text-[30px] leading-[1.1] font-medium tracking-[-0.025em] text-foreground md:text-[40px]"
          >
            {title}
          </h3>
          <p className="mt-6 max-w-[720px] text-[17px] leading-[1.45] text-muted-foreground md:text-[20px]">
            {intro}
          </p>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-8 md:mt-14 lg:grid-cols-[minmax(0,1fr)_420px] lg:gap-16">
          {/* Frame + progress */}
          <div
            className={cn(
              "min-w-0 transition-[opacity,transform] delay-150 duration-700 ease-out",
              seen ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0",
            )}
          >
            <div className="transition-[transform,filter] duration-500 ease-out hover:-translate-y-1 hover:drop-shadow-[0_24px_40px_rgba(255,110,50,0.16)]">
              <div
                aria-hidden
                className="relative h-[380px] overflow-hidden rounded-t-md px-3 pt-3 sm:h-[480px] sm:px-6 sm:pt-6 lg:h-[600px] lg:px-10 lg:pt-10"
                style={{
                  background:
                    "radial-gradient(120% 90% at 15% 0%, #5a4744 0%, rgba(90,71,68,0) 60%), linear-gradient(160deg, #4a3b3b 0%, #3d3131 55%, #352a2b 100%)",
                }}
              >
                <div className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:radial-gradient(#fff_0.6px,transparent_0.6px)] [background-size:4px_4px]" />
                <div className="relative h-full overflow-hidden rounded-t-md border border-b-0 border-[#2e2a31] bg-[#161318] text-[12px] text-[#d9d6dc] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.7)]">
                  <div key={seen ? "seen" : "idle"} className="h-full">
                    {seen ? mock(active) : null}
                  </div>
                </div>
              </div>
              {/* Segmented progress bar */}
              <div className="flex h-[3px] gap-0" role="presentation">
                {items.map((it, i) => {
                  const c = SEG[i % SEG.length];
                  return (
                    <div
                      key={it.title}
                      className="relative h-full flex-1 overflow-hidden"
                      style={{ background: `${c}26` }}
                    >
                      {i < active && (
                        <div
                          className="absolute inset-0"
                          style={{ background: `${c}8c` }}
                        />
                      )}
                      {i === active && (
                        <div
                          key={`${active}-${reduced}`}
                          className="absolute inset-0 origin-left"
                          style={{
                            background: c,
                            animation: reduced
                              ? undefined
                              : `b-fill ${SLIDE_MS}ms linear forwards`,
                            animationPlayState: running ? "running" : "paused",
                            boxShadow: `0 0 10px ${c}`,
                          }}
                          onAnimationEnd={next}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Feature list */}
          <div className="flex flex-col lg:-mt-3">
            <ul className="flex flex-col gap-1 lg:gap-3">
              {items.map((it, i) => {
                const on = i === active;
                return (
                  <li
                    key={it.title}
                    className={cn(
                      "transition-[opacity,transform] duration-700 ease-out",
                      seen
                        ? "translate-y-0 opacity-100"
                        : "translate-y-3 opacity-0",
                    )}
                    style={{ transitionDelay: `${250 + i * 90}ms` }}
                  >
                    <button
                      type="button"
                      onClick={() => setActive(i)}
                      aria-pressed={on}
                      className={cn(
                        "group relative w-full rounded-sm py-3 pl-4 text-left transition-colors duration-300 outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
                      )}
                    >
                      <span
                        aria-hidden
                        className="absolute top-3 bottom-3 left-0 w-[2px] rounded-full transition-all duration-500"
                        style={{
                          background: on
                            ? SEG[i % SEG.length]
                            : "var(--border)",
                          opacity: on ? 1 : 0.6,
                        }}
                      />
                      <span
                        className={cn(
                          "block text-[17px] leading-snug font-semibold transition-colors duration-300",
                          on
                            ? "text-foreground"
                            : "text-foreground/60 group-hover:text-foreground/85",
                          it.dotted &&
                            "underline decoration-dotted decoration-[1.5px] underline-offset-[5px]",
                          it.dotted &&
                            (on
                              ? "decoration-foreground/60"
                              : "decoration-foreground/30"),
                        )}
                      >
                        {it.title}
                      </span>
                      <span
                        className={cn(
                          "mt-1.5 block text-[15px] leading-[1.45] transition-colors duration-300 md:text-[16px]",
                          on
                            ? "text-muted-foreground"
                            : "text-muted-foreground/55 group-hover:text-muted-foreground/80",
                        )}
                      >
                        {it.body}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="mt-6 pl-4 lg:mt-8">
              <Link
                href={cta.href}
                className="inline-flex h-10 items-center gap-2 rounded-sm border border-input bg-transparent px-4 text-[15px] font-medium text-foreground transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none"
              >
                {cta.label}
                <ArrowRight className="size-4" aria-hidden />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------- small shared mock atoms ---------- */

export function OwlAvatar({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "grid size-7 shrink-0 place-items-center rounded-[5px] bg-[#ff570a]",
        className,
      )}
    >
      <svg viewBox="0 0 32 32" className="size-[18px]">
        <path
          d="M4 9 L8 3 L12 7 L20 7 L24 3 L28 9 Q30 20 22 28 L10 28 Q2 20 4 9 Z"
          fill="#fff"
        />
        <circle cx="11.5" cy="14" r="4.6" fill="#ff570a" />
        <circle cx="20.5" cy="14" r="4.6" fill="#ff570a" />
        <circle cx="11.5" cy="14" r="2" fill="#fff" />
        <circle cx="20.5" cy="14" r="2" fill="#fff" />
        <path d="M14.3 19.5 L16 22.5 L17.7 19.5 Z" fill="#ff570a" />
      </svg>
    </span>
  );
}

export function UserAvatar({
  initials,
  color = "#6b6572",
}: {
  initials: string;
  color?: string;
}) {
  return (
    <span
      className="grid size-7 shrink-0 place-items-center rounded-[5px] text-[10px] font-semibold text-white"
      style={{ background: color }}
    >
      {initials}
    </span>
  );
}

export function Tag({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "rounded-full border border-[#3a3640] px-1.5 py-px font-mono text-[10px] leading-4 text-[#a9a4ae]",
        className,
      )}
    >
      {children}
    </span>
  );
}

export type Severity = "critical" | "major" | "minor" | "trivial";
export const SEV_COLOR: Record<Severity, string> = {
  critical: "#ff6467",
  major: "#ff8a3d",
  minor: "#ffc53d",
  trivial: "#6aa8ff",
};

/** Outlined severity chip, as on the review page ("Major severity"). */
export function Sev({
  level,
  suffix = "",
}: {
  level: Severity;
  suffix?: string;
}) {
  const c = SEV_COLOR[level];
  return (
    <span
      className="inline-flex items-center rounded-[4px] border px-1.5 whitespace-nowrap py-px text-[10.5px] leading-4 font-medium capitalize"
      style={{ color: c, borderColor: `${c}99` }}
    >
      {level}
      {suffix}
    </span>
  );
}

/** Counts up to `to` once mounted (instant under reduced motion). */
export function Tick({
  to,
  ms = 1100,
  format = (n: number) => String(Math.round(n)),
}: {
  to: number;
  ms?: number;
  format?: (n: number) => string;
}) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setV(to);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / ms);
      setV(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to, ms]);
  return <>{format(v)}</>;
}

/** Green "Completed" / "Open" status pill used across the app. */
export function StatusPill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-[4px] border border-[#46e1a5]/50 bg-[#46e1a5]/10 px-1.5 py-px text-[10.5px] leading-4 font-medium text-[#85f9c5]">
      <span className="size-1.5 rounded-full bg-[#46e1a5]" />
      {children}
    </span>
  );
}

/** Top bar used by the "PR conversation" style mocks: repo #n on the left, n/N on the right. */
export function MockBar({
  left,
  right,
}: {
  left: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex h-10 items-center justify-between border-b border-[#2a262d] bg-[#1b181e] px-4 font-mono text-[11.5px] text-[#a9a4ae]">
      <div className="flex min-w-0 items-center gap-2 truncate">{left}</div>
      {right && <div className="shrink-0 tabular-nums">{right}</div>}
    </div>
  );
}
