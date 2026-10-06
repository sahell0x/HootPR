"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CodeGraph } from "@/components/cr/landing/c-graph";
import { CReveal, useInView } from "@/components/cr/landing/c-reveal";
import { CONTAINER, Eyebrow } from "@/components/cr/landing/shared";
import { cn } from "@/lib/utils";

const STAGES = [
  {
    title: "Sandboxed tools",
    body: "Linters and security scanners run against your diff in an isolated container before any model reads a line.",
  },
  {
    title: "Code graph",
    body: "HootPR maps the symbols a change touches: who calls them, what they call, and which files import them.",
  },
  {
    title: "Learnings & path instructions",
    body: "Rules you taught it by replying, plus path instructions and ast-grep rules from .hootpr.yaml and your org defaults.",
  },
  {
    title: "Specialist agents",
    body: "Focused reviewers for correctness, security, performance and tests work the same context in parallel.",
  },
  {
    title: "Judge model",
    body: "A separate judge re-reads every draft finding and drops the false positives before anything is posted.",
  },
];

const DURATION = 5500;
/** Scroll distance (in viewport heights) spent on each stage while the box is pinned on desktop. */
const STAGE_VH = 55;

export function ContextSection() {
  const [active, setActive] = useState(0);
  const [cycle, setCycle] = useState(0); // bumps to restart the progress bar
  const [paused, setPaused] = useState(false);
  const [ref, inView] = useInView<HTMLDivElement>(0.3);
  const [reduced, setReduced] = useState(false);
  // Desktop: the box is pinned and the page scroll picks the stage (like coderabbit.ai). Mobile: tap / timer.
  const [scrollMode, setScrollMode] = useState(false);
  const [stageProgress, setStageProgress] = useState(0); // 0..1 within the active stage, drives the indicator
  const track = useRef<HTMLDivElement>(null);
  const running = inView && !paused && !scrollMode;

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const wide = window.matchMedia("(min-width: 1024px)");
    const on = () => {
      setReduced(mq.matches);
      setScrollMode(wide.matches && !mq.matches);
    };
    on();
    mq.addEventListener("change", on);
    wide.addEventListener("change", on);
    return () => {
      mq.removeEventListener("change", on);
      wide.removeEventListener("change", on);
    };
  }, []);

  // Map scroll position inside the tall track to a stage and the progress through it.
  useEffect(() => {
    if (!scrollMode) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const el = track.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const span = el.offsetHeight - window.innerHeight;
      const p = span > 0 ? Math.min(1, Math.max(0, -r.top / span)) : 0;
      const pos = p * STAGES.length;
      const i = Math.min(STAGES.length - 1, Math.floor(pos));
      setActive(i);
      setStageProgress(i === STAGES.length - 1 && p >= 1 ? 1 : pos - i);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [scrollMode]);

  // In scroll mode, clicking a stage smoothly scrolls the page to that stage.
  const scrollToStage = useCallback((i: number) => {
    const el = track.current;
    if (!el) return;
    const span = el.offsetHeight - window.innerHeight;
    const top =
      el.getBoundingClientRect().top +
      window.scrollY +
      (span * (i + 0.5)) / STAGES.length;
    window.scrollTo({ top, behavior: "smooth" });
  }, []);

  const advance = () => {
    setActive((a) => (a + 1) % STAGES.length);
    setCycle((c) => c + 1);
  };

  const select = (i: number) => {
    if (scrollMode) return scrollToStage(i);
    setActive(i);
    setCycle((c) => c + 1);
  };

  return (
    <section
      id="context"
      aria-labelledby="context-title"
      className="scroll-mt-20"
    >
      <style>{`@keyframes cx-fill { from { transform: scaleY(0); } to { transform: scaleY(1); } }`}</style>
      <div className={cn(CONTAINER, "py-20 md:py-24")}>
        <CReveal>
          <Eyebrow>How HootPR thinks</Eyebrow>
          <h2
            id="context-title"
            className="mt-4 text-[32px] leading-[1.1] font-medium tracking-[-0.03em] sm:text-[40px]"
          >
            Context before comments.
          </h2>
          <p className="mt-5 max-w-[62ch] text-lg leading-7 text-muted-foreground">
            Every review is assembled in stages. Tools gather facts, the graph
            adds reach, your rules add taste, and a judge keeps only what holds
            up.
          </p>
        </CReveal>

        <div
          ref={track}
          className="mt-14"
          style={
            scrollMode
              ? { height: `calc(100vh + ${STAGES.length * STAGE_VH}vh)` }
              : undefined
          }
        >
          <CReveal
            delay={120}
            className={cn(scrollMode && "sticky top-[calc(50vh-310px)]")}
          >
            <div
              ref={ref}
              onMouseEnter={() => setPaused(true)}
              onMouseLeave={() => setPaused(false)}
              className="grid overflow-hidden rounded-md border lg:grid-cols-[300px_1fr]"
            >
              <ul
                className="flex flex-col border-t lg:border-t-0 lg:border-r"
                role="tablist"
                aria-label="Review stages"
              >
                {STAGES.map((s, i) => {
                  const on = i === active;
                  return (
                    <li key={s.title} className="relative flex-1">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={on}
                        aria-controls="context-visual"
                        onClick={() => select(i)}
                        className={cn(
                          "flex h-full w-full flex-col items-start px-6 py-5 text-left transition-colors lg:px-7 lg:py-7",
                          on ? "bg-white/[0.02]" : "hover:bg-white/[0.015]",
                        )}
                      >
                        <span className="flex items-center gap-3">
                          <span
                            className={cn(
                              "font-mono text-[11px]",
                              on ? "text-primary" : "text-faint",
                            )}
                          >
                            {String(i + 1).padStart(2, "0")}
                          </span>
                          <span
                            className={cn(
                              "text-[16px] font-medium transition-colors",
                              on
                                ? "text-foreground"
                                : "text-muted-foreground/70",
                            )}
                          >
                            {s.title}
                          </span>
                        </span>
                        <span
                          className={cn(
                            "grid transition-[grid-template-rows,opacity] duration-500 ease-out",
                            on
                              ? "grid-rows-[1fr] opacity-100"
                              : "grid-rows-[0fr] opacity-0",
                          )}
                        >
                          <span className="overflow-hidden">
                            <span className="block pt-2.5 pl-[25px] text-[15px] leading-6 text-muted-foreground">
                              {s.body}
                            </span>
                          </span>
                        </span>
                      </button>
                      {/* Orange indicator on the column edge; fills while the stage is showing. */}
                      <span
                        aria-hidden
                        className={cn(
                          "absolute top-0 bottom-0 left-0 w-[2px] bg-primary/25 lg:right-[-1px] lg:left-auto",
                          on ? "opacity-100" : "opacity-0",
                        )}
                      >
                        {on && reduced ? (
                          <span className="absolute inset-0 bg-primary" />
                        ) : null}
                        {on && scrollMode ? (
                          <span
                            className="absolute inset-0 origin-top bg-primary transition-transform duration-150 ease-out"
                            style={{ transform: `scaleY(${stageProgress})` }}
                          />
                        ) : null}
                        {on && !reduced && !scrollMode ? (
                          <span
                            key={cycle}
                            className="absolute inset-0 origin-top bg-primary"
                            onAnimationEnd={advance}
                            style={{
                              animationName: "cx-fill",
                              animationDuration: `${DURATION}ms`,
                              animationTimingFunction: "linear",
                              animationFillMode: "forwards",
                              animationPlayState: running
                                ? "running"
                                : "paused",
                            }}
                          />
                        ) : null}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <div
                id="context-visual"
                role="tabpanel"
                aria-label={STAGES[active]?.title}
                className="relative order-first flex items-center justify-center px-2 py-8 sm:px-8 lg:order-none lg:py-12"
              >
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.025)_1px,transparent_1px)] [background-size:18px_18px]"
                />
                <div className="relative w-full max-w-[720px]">
                  <CodeGraph stage={active} />
                </div>
              </div>
            </div>
          </CReveal>
        </div>
      </div>
    </section>
  );
}
