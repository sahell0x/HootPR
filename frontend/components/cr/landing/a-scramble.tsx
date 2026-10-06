"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const GLYPHS = "abcdefghijklmnopqrstuvwxyz<>/{}[]=+*#$%&!?;:_~^";
const TICK = 55;

function words(text: string) {
  const out: { word: string; start: number }[] = [];
  let start = 0;
  for (const word of text.split(" ")) {
    out.push({ word, start });
    start += Array.from(word).length + 1;
  }
  return out;
}

type Cell ={ g: string; tone: 0 | 1; dy: number } | null;

/** Decode effect: each character cycles through random glyphs (mint / red, jumping a little)
 * and then settles, left to right. Layout never shifts: the real character is always in the
 * flow (it is the only text in the DOM); the glyph is painted on top via ::after. Purely
 * decorative — the parent heading carries the accessible name. */
export function Scramble({ text, className, delay = 350 }: { text: string; className?: string; delay?: number }) {
  const chars = Array.from(text);
  const [cells, setCells] = useState<Cell[]>(() => chars.map(() => null));
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const running = useRef(false);

  const run = useCallback(() => {
    if (running.current) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    running.current = true;
    const n = chars.length;
    // Tick at which each character locks in: staggered left→right with jitter.
    const settle = chars.map((_, i) => 12 + i * 3 + Math.floor(Math.random() * 10));
    let t = 0;
    timer.current = setInterval(() => {
      t += 1;
      const next: Cell[] = chars.map((c, i) => {
        if (c === " " || c === "." || t >= settle[i]!) return null;
        return {
          g: GLYPHS[Math.floor(Math.random() * GLYPHS.length)]!,
          tone: Math.random() < 0.72 ? 0 : 1,
          dy: Math.round((Math.random() - 0.5) * 0.5 * 100) / 100,
        };
      });
      setCells(next);
      if (next.every((x) => x === null) && t > Math.max(...settle, n)) {
        if (timer.current) clearInterval(timer.current);
        running.current = false;
      }
    }, TICK);
  }, [chars]);

  useEffect(() => {
    const id = setTimeout(run, delay);
    // Decode again every so often, like a signal re-locking.
    const again = setInterval(run, 9000);
    return () => {
      clearTimeout(id);
      clearInterval(again);
      if (timer.current) clearInterval(timer.current);
      running.current = false;
    };
    // Mount-only; `chars` is derived from a constant string.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <span aria-hidden className={cn("inline", className)} onMouseEnter={run}>
      {words(text).map(({ word, start }, w) => (
        <span key={w}>
          {w > 0 ? " " : null}
          {/* nowrap: inline-block glyphs must not become line-break opportunities inside a word */}
          <span className="whitespace-nowrap">
            {Array.from(word).map((c, j) => {
              const i = start + j;
              const cell = cells[i];
              if (!cell) return <span key={i}>{c}</span>;
              return (
                <span
                  key={i}
                  data-g={cell.g}
                  style={{ ["--dy" as string]: `${cell.dy}em` }}
                  className={cn(
                    "relative inline-block text-transparent",
                    "after:absolute after:inset-0 after:translate-y-(--dy) after:text-center after:content-[attr(data-g)]",
                    cell.tone === 0 ? "after:text-success" : "after:text-destructive",
                  )}
                >
                  {c}
                </span>
              );
            })}
          </span>
        </span>
      ))}
    </span>
  );
}
