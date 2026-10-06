"use client";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import {
  BookOpen,
  FileText,
  FolderGit2,
  GitPullRequest,
  Layers,
  LayoutGrid,
  Search,
  Shield,
  type LucideIcon,
} from "lucide-react";
import { OwlMark } from "@/components/brand";
import { cn } from "@/lib/utils";

/* Building blocks for the hero's product mocks. They copy the real app's look (app shell,
 * status chips, severity badges, code view) with example data. `live` = the pane is the
 * active one: run its entrance motion; otherwise render the settled state. */

export const MOCK_CSS = `
@keyframes hp-rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes hp-caret{50%{opacity:0}}
.hp-rise{animation:hp-rise .55s cubic-bezier(.2,.7,.2,1) both;animation-delay:var(--d,0ms)}
.hp-caret{display:inline-block;width:.45em;height:1em;margin-left:1px;vertical-align:-.15em;background:currentColor;animation:hp-caret 1s steps(1) infinite}
`;

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/** Streams `text` in word-sized chunks, like a model answer. */
export function useStream(text: string, live: boolean, { delay = 0, speed = 28 } = {}) {
  const reduced = useReducedMotion();
  const animate = live && !reduced;
  const [n, setN] = useState(animate ? 0 : text.length);
  useEffect(() => {
    if (!animate) {
      setN(text.length);
      return;
    }
    setN(0);
    let i = 0;
    let iv: ReturnType<typeof setInterval> | undefined;
    const t = setTimeout(() => {
      iv = setInterval(() => {
        i = Math.min(text.length, i + 1 + Math.floor(Math.random() * 3));
        setN(i);
        if (i >= text.length && iv) clearInterval(iv);
      }, speed);
    }, delay);
    return () => {
      clearTimeout(t);
      if (iv) clearInterval(iv);
    };
  }, [animate, text, delay, speed]);
  return { shown: text.slice(0, n), done: n >= text.length };
}

export function Streamed({ text, live, delay, speed, className }: { text: string; live: boolean; delay?: number; speed?: number; className?: string }) {
  const { shown, done } = useStream(text, live, { delay, speed });
  return (
    <span className={className}>
      {shown}
      {!done ? <span className="hp-caret text-primary/80" aria-hidden /> : null}
    </span>
  );
}

/** Number that ticks up from 0 when live. */
export function Counter({ to, live, duration = 1100, delay = 0, decimals = 0 }: { to: number; live: boolean; duration?: number; delay?: number; decimals?: number }) {
  const reduced = useReducedMotion();
  const animate = live && !reduced;
  const [v, setV] = useState(animate ? 0 : to);
  useEffect(() => {
    if (!animate) {
      setV(to);
      return;
    }
    setV(0);
    let raf = 0;
    const t = setTimeout(() => {
      const start = performance.now();
      const step = (now: number) => {
        const p = Math.min(1, (now - start) / duration);
        setV(to * (1 - Math.pow(1 - p, 3)));
        if (p < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, delay);
    return () => {
      clearTimeout(t);
      cancelAnimationFrame(raf);
    };
  }, [animate, to, duration, delay]);
  return <span className="tabular-nums">{v.toFixed(decimals)}</span>;
}

/** Staggered rise-in wrapper (only when live). */
export function Rise({ live, i = 0, step = 70, base = 0, className, children }: { live: boolean; i?: number; step?: number; base?: number; className?: string; children: ReactNode }) {
  return (
    <div className={cn(live && "hp-rise", className)} style={live ? ({ "--d": `${base + i * step}ms` } as CSSProperties) : undefined}>
      {children}
    </div>
  );
}

const RAIL: { key: string; icon: LucideIcon }[] = [
  { key: "repos", icon: FolderGit2 },
  { key: "dashboard", icon: LayoutGrid },
  { key: "reviews", icon: GitPullRequest },
  { key: "change-stack", icon: Layers },
  { key: "reports", icon: FileText },
  { key: "learnings", icon: BookOpen },
  { key: "security", icon: Shield },
];

/** The app shell in miniature: icon rail + breadcrumb top bar. */
export function AppWindow({ crumbs, nav, children, className }: { crumbs: string[]; nav: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-md border bg-background shadow-2xl shadow-black/40", className)}>
      <div className="flex h-9 items-center gap-2 border-b bg-sidebar px-3 text-[11.5px]">
        <OwlMark className="size-4 shrink-0" />
        <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
          {crumbs.map((c, i) => (
            <span key={c} className={cn("flex min-w-0 items-center gap-1.5", i < crumbs.length - 1 && "shrink-0", i > 0 && i < crumbs.length - 1 && "hidden @md:flex")}>
              {i > 0 ? <span className="text-faint">/</span> : null}
              <span className={cn("truncate", i === crumbs.length - 1 && "font-medium text-foreground")}>{c}</span>
            </span>
          ))}
        </span>
        <span className="ml-auto hidden h-6 w-36 shrink-0 items-center gap-1.5 rounded-sm border bg-background px-2 text-faint @xl:flex">
          <Search className="size-3" aria-hidden /> Search
          <span className="ml-auto font-mono text-[9.5px]">⌘K</span>
        </span>
      </div>
      <div className="flex">
        <div className="hidden w-11 shrink-0 flex-col items-center gap-1 border-r bg-sidebar py-2.5 @xl:flex">
          {RAIL.map((r) => (
            <span
              key={r.key}
              className={cn(
                "grid size-7 place-items-center rounded-sm text-faint",
                r.key === nav && "bg-accent text-foreground ring-1 ring-border",
              )}
            >
              <r.icon className="size-3.5" aria-hidden />
            </span>
          ))}
        </div>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}

export function StatusChip({ tone = "success", children }: { tone?: "success" | "caution" | "destructive"; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-sm border px-1.5 text-[11px] leading-[18px]",
        tone === "success" && "border-success/35 bg-success/10 text-success",
        tone === "caution" && "border-caution/35 bg-caution/10 text-caution",
        tone === "destructive" && "border-destructive/35 bg-destructive/10 text-destructive",
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

/** "Major severity" style badge from the findings list. */
export function SeverityBadge({ sev }: { sev: "Critical" | "Major" | "Minor" | "Nitpick" }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-sm border px-1.5 text-[11px] leading-[20px]",
        sev === "Critical" && "border-destructive/60 text-destructive",
        sev === "Major" && "border-primary/70 text-primary",
        sev === "Minor" && "border-caution/50 text-caution",
        sev === "Nitpick" && "border-border text-muted-foreground",
      )}
    >
      {sev} severity
    </span>
  );
}

export function FileChip({ children }: { children: ReactNode }) {
  return <span className="rounded-sm border bg-subtle px-1.5 font-mono text-[10.5px] leading-[18px] text-muted-foreground">{children}</span>;
}

/* Code-view tokens (same palette as the app's diff viewer). */
export const KW = "text-[#7aa2f7]";
export const STR = "text-[#f0a35e]";
export const FN = "text-[#c3a6ff]";
