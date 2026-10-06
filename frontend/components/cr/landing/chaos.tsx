"use client";
import { useEffect, useRef, useState } from "react";
import { CONTAINER } from "@/components/cr/landing/shared";
import { cn } from "@/lib/utils";

/* "Why now": many pull requests (left) → many coloured threads → one bright beam through HootPR. */

const W = 1216;
const H = 520;
const DIV_X = 600; // vertical divider where the threads converge
const CY = H / 2;
const CELL = 44;
const GX = 20;
const GY = 62;
const COLS = 7;
const ROWS = 9;

const COLORS = ["#ff6467", "#46e1a5", "#ffc53d", "#a78bfa", "#85f9c5", "#ff8a4c"];
// Lane offset (px from the centre line) for each colour where threads meet the divider and continue as the beam.
const LANES: Record<string, number> = {
  "#ff6467": -10,
  "#ffc53d": -6,
  "#46e1a5": -2,
  "#a78bfa": 2,
  "#85f9c5": 6,
  "#ff8a4c": 10,
};

function prng(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Icon = { x: number; y: number; lit: boolean };
type Thread = { d: string; x0: number; color: string; width: number; opacity: number; dur: number; delay: number };

// Built once at module load with a fixed seed, so server and client render the same SVG.
const { ICONS, THREADS } = (() => {
  const r = prng(42);
  const icons: Icon[] = [];
  for (let row = 0; row < ROWS; row++) {
    for (let col = 0; col < COLS; col++) {
      const edge = Math.abs(row - (ROWS - 1) / 2) / ((ROWS - 1) / 2); // 0 centre → 1 top/bottom
      if (r() < 0.5 - edge * 0.12) {
        icons.push({ x: GX + col * CELL + CELL / 2, y: GY + row * CELL + CELL / 2, lit: r() < 0.55 });
      }
    }
  }
  const threads: Thread[] = [];
  icons.forEach((ic, i) => {
    const count = ic.lit ? (r() < 0.45 ? 2 : 1) : r() < 0.25 ? 1 : 0;
    for (let k = 0; k < count; k++) {
      const x0 = ic.x + 16;
      const y0 = ic.y + (k === 0 ? 0 : (r() - 0.5) * 16);
      const color = COLORS[(i + k * 3) % COLORS.length]!;
      const y1 = CY + LANES[color]!;
      const span = DIV_X - x0;
      const c1x = x0 + span * (0.35 + r() * 0.2);
      const c2x = DIV_X - span * (0.28 + r() * 0.15);
      threads.push({
        d: `M${x0.toFixed(1)} ${y0.toFixed(1)} C${c1x.toFixed(1)} ${y0.toFixed(1)} ${c2x.toFixed(1)} ${y1.toFixed(1)} ${DIV_X} ${y1.toFixed(1)}`,
        x0,
        color,
        width: ic.lit ? 1.2 : 0.8,
        opacity: ic.lit ? 1 : 0.5,
        dur: 2.6 + r() * 3,
        delay: -r() * 6,
      });
    }
  });
  return { ICONS: icons, THREADS: threads };
})();

const BEAM = Object.entries(LANES).map(([c, o]) => ({ c, o }));

const CSS = `
@keyframes hp-flow{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}
@media (prefers-reduced-motion: no-preference){
  .hp-pulse{animation:hp-flow var(--dur) linear infinite;animation-delay:var(--delay)}
}
@media (prefers-reduced-motion: reduce){.hp-pulse{display:none}}
`;

function PrGlyph({ x, y, lit }: Icon) {
  return (
    <g transform={`translate(${x - 14} ${y - 14})`} opacity={lit ? 1 : 0.45}>
      <rect x={0.5} y={0.5} width={27} height={27} rx={4} fill="#141116" stroke={lit ? "#3d3943" : "#2a272f"} />
      <g transform="translate(7 7) scale(0.58)" fill="none" stroke={lit ? "#9d98a3" : "#5b5761"} strokeWidth={2.2} strokeLinecap="round">
        <circle cx={18} cy={18} r={3} />
        <circle cx={6} cy={6} r={3} />
        <path d="M13 6h3a2 2 0 0 1 2 2v7" />
        <path d="M6 9v12" />
      </g>
    </g>
  );
}

function ChaosArt({ on }: { on: boolean }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMinYMid slice" className="absolute inset-0 h-full w-full" aria-hidden>
      <defs>
        <pattern id="hp-grid" width={CELL} height={CELL} patternUnits="userSpaceOnUse" x={GX} y={GY}>
          <path d={`M${CELL} 0H0V${CELL}`} fill="none" stroke="#ffffff" strokeOpacity={0.07} />
        </pattern>
        <radialGradient id="hp-grid-fade" cx="0.3" cy="0.5" r="0.62">
          <stop offset="0" stopColor="#fff" />
          <stop offset="1" stopColor="#fff" stopOpacity={0} />
        </radialGradient>
        <mask id="hp-grid-mask">
          <rect x={0} y={0} width={DIV_X} height={H} fill="url(#hp-grid-fade)" />
        </mask>
        {THREADS.map((t, i) => (
          <linearGradient key={i} id={`hp-t${i}`} gradientUnits="userSpaceOnUse" x1={t.x0} y1={0} x2={DIV_X} y2={0}>
            <stop offset="0" stopColor={t.color} stopOpacity={0} />
            <stop offset="0.5" stopColor={t.color} stopOpacity={0.22 * t.opacity} />
            <stop offset="1" stopColor={t.color} stopOpacity={0.55 * t.opacity} />
          </linearGradient>
        ))}
        {BEAM.map((b, i) => (
          <linearGradient key={i} id={`hp-b${i}`} gradientUnits="userSpaceOnUse" x1={DIV_X} y1={0} x2={W} y2={0}>
            <stop offset="0" stopColor={b.c} stopOpacity={0.85} />
            <stop offset="0.5" stopColor={b.c} stopOpacity={0.4} />
            <stop offset="1" stopColor={b.c} stopOpacity={0} />
          </linearGradient>
        ))}
        <linearGradient id="hp-glow" gradientUnits="userSpaceOnUse" x1={DIV_X - 40} y1={0} x2={W} y2={0}>
          <stop offset="0" stopColor="#ff8a4c" stopOpacity={0} />
          <stop offset="0.08" stopColor="#ff8a4c" stopOpacity={0.12} />
          <stop offset="0.4" stopColor="#46e1a5" stopOpacity={0.08} />
          <stop offset="0.75" stopColor="#a78bfa" stopOpacity={0.04} />
          <stop offset="1" stopColor="#a78bfa" stopOpacity={0} />
        </linearGradient>
        <linearGradient id="hp-divider" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity={0} />
          <stop offset="0.5" stopColor="#fff" stopOpacity={0.14} />
          <stop offset="1" stopColor="#fff" stopOpacity={0} />
        </linearGradient>
        <filter id="hp-blur" x="-10%" y="-400%" width="120%" height="900%">
          <feGaussianBlur stdDeviation="5" />
        </filter>
      </defs>

      {/* Faint grid, fading out from its centre. */}
      <rect x={0} y={0} width={DIV_X} height={H} fill="url(#hp-grid)" mask="url(#hp-grid-mask)" />

      {/* Threads: drawn in on first view, then light pulses run along them. */}
      <g fill="none" strokeLinecap="round">
        {THREADS.map((t, i) => (
          <path
            key={i}
            d={t.d}
            stroke={`url(#hp-t${i})`}
            strokeWidth={t.width}
            pathLength={1}
            strokeDasharray="1"
            style={{
              strokeDashoffset: on ? 0 : 1,
              transition: `stroke-dashoffset 1.8s cubic-bezier(0.3,0.7,0.2,1) ${(i % 9) * 0.07}s`,
            }}
          />
        ))}
        {THREADS.map((t, i) =>
          i % 2 === 0 ? (
            <path
              key={`p${i}`}
              d={t.d}
              className="hp-pulse"
              stroke={t.color}
              strokeOpacity={on ? 0.9 * t.opacity : 0}
              strokeWidth={t.width + 0.4}
              pathLength={1}
              strokeDasharray="0.1 0.9"
              strokeDashoffset={1}
              style={{ ["--dur" as string]: `${t.dur}s`, ["--delay" as string]: `${t.delay}s`, transition: "stroke-opacity 1s 1.2s" }}
            />
          ) : null,
        )}
      </g>

      {/* PR icons sit on top of the threads' faded tails. */}
      {ICONS.map((ic, i) => (
        <PrGlyph key={i} {...ic} />
      ))}

      {/* Divider. */}
      <line x1={DIV_X} y1={50} x2={DIV_X} y2={H - 50} stroke="url(#hp-divider)" />

      {/* The beam: one bundle of colour continuing right. */}
      <g
        style={{
          opacity: on ? 1 : 0,
          transform: on ? "none" : "scaleX(0.4)",
          transformOrigin: `${DIV_X}px ${CY}px`,
          transition: "opacity 1s 0.9s, transform 1.4s cubic-bezier(0.3,0.7,0.2,1) 0.9s",
        }}
      >
        <line x1={DIV_X} y1={CY} x2={W} y2={CY} stroke="url(#hp-glow)" strokeWidth={30} filter="url(#hp-blur)" />
        {BEAM.map((b, i) => (
          <line key={i} x1={DIV_X} y1={CY + b.o} x2={W} y2={CY + b.o} stroke={`url(#hp-b${i})`} strokeWidth={1.2} />
        ))}
        {BEAM.map((b, i) =>
          i % 2 === 0 ? (
            <line
              key={`bp${i}`}
              x1={DIV_X}
              y1={CY + b.o}
              x2={W}
              y2={CY + b.o}
              className="hp-pulse"
              stroke={b.c}
              strokeOpacity={0.8}
              strokeWidth={1.4}
              pathLength={1}
              strokeDasharray="0.08 0.92"
              strokeDashoffset={1}
              style={{ ["--dur" as string]: `${3 + i * 0.4}s`, ["--delay" as string]: `${-i * 0.7}s` }}
            />
          ) : null,
        )}
      </g>
    </svg>
  );
}

export function ChaosSection() {
  const ref = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e?.isIntersecting) {
          setOn(true);
          io.disconnect();
        }
      },
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section aria-labelledby="chaos-title" className="relative overflow-hidden py-16 sm:py-20 lg:py-24">
      <style>{CSS}</style>
      <div className={cn(CONTAINER, "relative")}>
        <div ref={ref} className="relative">
          <div className="relative -mx-4 aspect-[700/520] sm:mx-0 lg:aspect-[1216/520]">
            <ChaosArt on={on} />
          </div>
          <div className="relative mt-6 flex flex-col gap-5 lg:absolute lg:inset-y-0 lg:right-0 lg:left-[55%] lg:mt-0 lg:grid lg:grid-rows-2 lg:gap-0">
            <h2
              id="chaos-title"
              className="text-[32px] leading-[1.08] font-medium tracking-[-0.025em] text-foreground sm:text-[40px] lg:self-end lg:pb-11"
            >
              Fast code. Faster reviews.
            </h2>
            <p className="max-w-[500px] text-[18px] leading-[1.5] text-muted-foreground sm:text-[20px] lg:self-start lg:pt-11">
              Coding agents open more pull requests, and bigger ones, than any team can read line by line. HootPR reads
              every one the moment it opens.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
