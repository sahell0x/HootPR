"use client";

/**
 * Mini product mocks for the "More ways" bento. Each mirrors a real HootPR screen or PR comment
 * (billing ledger, dashboard, reports, finishing touches, pre-merge checks, @hootpr chat) with
 * example data. Animations start once the mock scrolls into view.
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import {
  CalendarClock,
  CornerDownRight,
  FileText,
  FlaskConical,
  GitPullRequest,
  Mail,
} from "lucide-react";
import { OwlMark } from "@/components/brand";
import { useInView } from "@/components/cr/landing/c-reveal";
import { cn } from "@/lib/utils";

const MOCK = "min-w-0 rounded-md border border-white/[0.07] bg-[#0f0d11] font-sans text-[12px] leading-[1.45]";

/** Staggered appear: children fade/slide in when `on` becomes true. */
function Appear({ on, delay = 0, children, className }: { on: boolean; delay?: number; children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "transition-[opacity,transform] duration-500 ease-out motion-reduce:transform-none motion-reduce:opacity-100",
        on ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0",
        className,
      )}
      style={{ transitionDelay: on ? `${delay}ms` : "0ms" }}
    >
      {children}
    </div>
  );
}

function useReducedMotion() {
  const [r, setR] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setR(mq.matches);
  }, []);
  return r;
}

/** Counts from 0 to `to` once `on` is true. */
function CountUp({ to, on, decimals = 0, duration = 1200, delay = 0 }: { to: number; on: boolean; decimals?: number; duration?: number; delay?: number }) {
  const reduced = useReducedMotion();
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!on) return;
    if (reduced) {
      setV(to);
      return;
    }
    let raf = 0;
    let start = 0;
    const tick = (t: number) => {
      if (!start) start = t + delay;
      const p = Math.min(1, Math.max(0, (t - start) / duration));
      setV(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [on, to, duration, delay, reduced]);
  return <span className="tabular-nums">{v.toFixed(decimals)}</span>;
}

/** Types `text` out once `on` is true. */
function Typed({ text, on, speed = 28, delay = 0 }: { text: string; on: boolean; speed?: number; delay?: number }) {
  const reduced = useReducedMotion();
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!on) return;
    if (reduced) {
      setN(text.length);
      return;
    }
    const start = performance.now() + delay;
    const iv = window.setInterval(() => {
      const k = Math.max(0, Math.floor((performance.now() - start) / speed));
      setN(Math.min(text.length, k));
      if (k >= text.length) window.clearInterval(iv);
    }, speed);
    return () => window.clearInterval(iv);
  }, [on, text, speed, delay, reduced]);
  return (
    <>
      {text.slice(0, n)}
      {n < text.length ? <span className="ml-px inline-block h-[1.1em] w-[5px] translate-y-[2px] animate-pulse bg-foreground/60" /> : null}
    </>
  );
}

function OwlAvatar({ size = "size-6" }: { size?: string }) {
  return (
    <span className={cn("grid shrink-0 place-items-center rounded-full bg-primary/15", size)}>
      <OwlMark className="size-[65%]" />
    </span>
  );
}

function Avatar({ letter }: { letter: string }) {
  return (
    <span className="grid size-6 shrink-0 place-items-center rounded-full bg-[#2e2a36] text-[11px] font-medium text-foreground/80">
      {letter}
    </span>
  );
}

type Tone = "red" | "amber" | "mint" | "violet" | "neutral";
const TONE: Record<Tone, string> = {
  red: "border-[#ff6467]/30 bg-[#ff6467]/10 text-[#ff8a8c]",
  amber: "border-[#ffc53d]/30 bg-[#ffc53d]/10 text-[#ffc53d]",
  mint: "border-[#46e1a5]/30 bg-[#46e1a5]/10 text-[#6af0bb]",
  violet: "border-[#687ff5]/30 bg-[#687ff5]/12 text-[#9aa8ff]",
  neutral: "border-white/10 bg-white/[0.03] text-muted-foreground",
};
const DOT: Record<Tone, string> = {
  red: "bg-[#ff6467]",
  amber: "bg-[#ffc53d]",
  mint: "bg-[#46e1a5]",
  violet: "bg-[#687ff5]",
  neutral: "bg-faint",
};

function Chip({ tone, children, pulse, dot = true }: { tone: Tone; children: ReactNode; pulse?: boolean; dot?: boolean }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-px text-[10.5px] whitespace-nowrap", TONE[tone])}>
      {dot ? <span className={cn("size-1.5 rounded-full", DOT[tone], pulse && "animate-pulse")} /> : null}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ chat */

export function ChatMock() {
  const [ref, on] = useInView<HTMLDivElement>(0.35, true);
  return (
    <div ref={ref} className={cn(MOCK, "p-4")}>
      <div className="flex items-center gap-2 border-b border-white/[0.06] pb-3 text-muted-foreground">
        <GitPullRequest className="size-3.5 shrink-0 text-[#46e1a5]" />
        <span className="shrink-0 font-mono text-[11px]">acme/web #214</span>
        <span className="truncate text-foreground/80">fix(auth): refresh session tokens before expiry</span>
      </div>
      <Appear on={on} className="mt-3">
        <div className="rounded-sm border border-white/[0.06] bg-white/[0.015] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <OwlAvatar />
            <span className="font-medium text-foreground">hootpr</span>
            <span className="rounded-full border border-white/10 px-1.5 text-[10px] text-faint">bot</span>
            <Chip tone="red">P1</Chip>
            <span className="truncate font-mono text-[10.5px] text-faint">src/auth/session.ts · lines 48–52</span>
          </div>
          <p className="mt-2 pl-8 font-medium text-foreground/90">Concurrent refreshes can reuse a revoked token.</p>
          <p className="mt-1 pl-8 text-muted-foreground">
            Two requests that both see an expired token call <code className="font-mono text-foreground/85">refresh()</code>; the second
            one sends the token the first just revoked.
          </p>
        </div>
      </Appear>
      <div className="mt-3 space-y-3 pl-3 sm:pl-4">
        <Appear on={on} delay={700}>
          <div className="flex gap-2">
            <CornerDownRight className="mt-1 size-3.5 shrink-0 text-faint" />
            <Avatar letter="M" />
            <p className="min-w-0 text-muted-foreground">
              <span className="font-medium text-foreground">maya</span>{" "}
              <span className="text-primary">@hootpr</span> would a lock slow down every request?
            </p>
          </div>
        </Appear>
        <Appear on={on} delay={1500}>
          <div className="flex gap-2">
            <CornerDownRight className="mt-1 size-3.5 shrink-0 text-faint" />
            <OwlAvatar />
            <div className="min-w-0 text-muted-foreground">
              <span className="font-medium text-foreground">hootpr</span>{" "}
              <span className="text-primary">@maya</span> Only the refresh path. Share one in-flight promise per user, so reads never wait:
              <div className="mt-2 overflow-hidden rounded-sm border border-white/[0.06] font-mono text-[11px]">
                <div className="truncate bg-[#ff6467]/[0.08] px-2 py-0.5 text-[#ff9a9c]">- return await refresh(user)</div>
                <div className="truncate bg-[#46e1a5]/[0.08] px-2 py-0.5 text-[#7ef2c2]">+ return (inflight[user.id] ??= refresh(user))</div>
              </div>
            </div>
          </div>
        </Appear>
        <Appear on={on} delay={2300}>
          <div className="flex gap-2">
            <CornerDownRight className="mt-1 size-3.5 shrink-0 text-faint" />
            <Avatar letter="M" />
            <p className="min-w-0 text-muted-foreground">
              <span className="font-medium text-foreground">maya</span>{" "}
              <span className="text-primary">@hootpr</span> remember: auth helpers must be safe under concurrency.
            </p>
          </div>
        </Appear>
        <Appear on={on} delay={3100}>
          <div className="flex gap-2">
            <CornerDownRight className="mt-1 size-3.5 shrink-0 text-faint" />
            <OwlAvatar />
            <div className="min-w-0 flex-1 text-muted-foreground">
              <span className="font-medium text-foreground">hootpr</span> <span className="text-primary">@maya</span> Noted, I&apos;ll
              check auth helpers for this from now on.
              <div className="mt-2 rounded-sm border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
                <p className="text-[11px] text-foreground/85">▾ ✏️ Learnings added</p>
                <pre className="mt-1 overflow-hidden font-mono text-[10.5px] leading-4 whitespace-pre-wrap text-muted-foreground">
                  {"Learnt from: maya\nPR: acme/web#214\n\nLearning: auth helpers must be safe under concurrency."}
                </pre>
              </div>
            </div>
          </div>
        </Appear>
      </div>
    </div>
  );
}

/* ------------------------------------------------------- pre-merge checks */

export function ChecksMock() {
  const [ref, on] = useInView<HTMLDivElement>(0.4, true);
  const passed = [
    ["Title check", "The title is specific and reasonably short."],
    ["Description check", "The description explains the change."],
    ["Linked Issues check", "The changes address the linked issues."],
  ];
  return (
    <div ref={ref} className={cn(MOCK, "p-3.5")}>
      <div className="flex items-center gap-2 px-0.5">
        <OwlAvatar size="size-5" />
        <span className="font-medium text-foreground">Pre-merge checks</span>
        <span className="ml-auto">
          <Chip tone="amber">1 warning</Chip>
        </span>
      </div>
      <Appear on={on} delay={150} className="mt-3">
        <p className="text-[11.5px] text-muted-foreground">▾ ❌ Failed checks (1 warning)</p>
        <div className="mt-1.5 rounded-sm border border-[#ffc53d]/20 bg-[#ffc53d]/[0.04] px-2.5 py-2">
          <div className="flex items-center gap-2">
            <span className="font-medium text-foreground/90">Docstring Coverage</span>
            <span className="ml-auto text-[11px] text-[#ffc53d]">⚠️ Warning</span>
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Docstring coverage is 62.50% which is insufficient. The required threshold is 80.00%.
          </p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
            <div
              className="h-full rounded-full bg-[#ffc53d] transition-[width] duration-[1400ms] ease-out"
              style={{ width: on ? "62.5%" : "0%", transitionDelay: "400ms" }}
            />
          </div>
        </div>
      </Appear>
      <p className="mt-3 text-[11.5px] text-muted-foreground">▾ ✅ Passed checks (3 passed)</p>
      <ul className="mt-1.5 divide-y divide-white/[0.05] rounded-sm border border-white/[0.06]">
        {passed.map(([name, why], i) => (
          <li key={name}>
            <Appear on={on} delay={500 + i * 180} className="flex items-center gap-2 px-2.5 py-1.5">
              <span className="text-[11px]">✅</span>
              <span className="shrink-0 text-foreground/90">{name}</span>
              <span className="ml-auto truncate pl-2 text-[11px] text-faint">{why}</span>
            </Appear>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------ finishing touches */

export function FinishingMock() {
  const [ref, on] = useInView<HTMLDivElement>(0.4, true);
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!on) return;
    const t = window.setTimeout(() => setDone(true), 2600);
    return () => window.clearTimeout(t);
  }, [on]);
  return (
    <div ref={ref} className={cn(MOCK, "overflow-hidden")}>
      <div className="flex items-center gap-2 border-b border-white/[0.06] px-3 py-2.5">
        <Avatar letter="M" />
        <span className="min-w-0 truncate font-mono text-[11.5px]">
          <span className="text-primary">@hootpr</span>{" "}
          <span className="text-foreground/85">
            <Typed text="generate unit tests" on={on} />
          </span>
        </span>
      </div>
      <ul className="divide-y divide-white/[0.05]">
        <li>
          <Appear on={on} delay={900} className="flex items-start gap-2.5 px-3 py-2.5">
            <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md border border-white/10 bg-[#141116]">
              <FlaskConical className="size-3 text-muted-foreground" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-foreground/90">Unit tests</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {done ? "stacked PR #215 · 3 files" : "in progress"} · @maya · just now
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              {done ? <Chip tone="mint">Completed</Chip> : <Chip tone="violet" pulse>Running</Chip>}
              {done ? <Chip tone="mint" dot={false}>tests passed</Chip> : null}
            </div>
          </Appear>
        </li>
        <li>
          <Appear on={on} delay={1100} className="flex items-start gap-2.5 px-3 py-2.5">
            <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md border border-white/10 bg-[#141116]">
              <FileText className="size-3 text-muted-foreground" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-foreground/90">Docstrings</p>
              <p className="truncate text-[11px] text-muted-foreground">
                stacked PR #213 · 5 files · @dev · 1h ago
              </p>
            </div>
            <Chip tone="mint">Completed</Chip>
          </Appear>
        </li>
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------------- reports */

export function ReportMock() {
  const [ref, on] = useInView<HTMLDivElement>(0.4, true);
  return (
    <div ref={ref} className={cn(MOCK, "p-3")}>
      <div className="flex items-center gap-2 px-0.5">
        <CalendarClock className="size-3.5 text-muted-foreground" />
        <span className="text-foreground/90">Weekly digest</span>
        <span className="text-faint">· Mondays 09:00</span>
        <span className="ml-auto">
          <Chip tone="mint">Active</Chip>
        </span>
      </div>
      <div className="mt-2.5 rounded-sm border border-white/[0.06] bg-white/[0.02] px-2.5 py-2 font-mono text-[11px] text-foreground/85">
        <Typed text="Summarize this week's security findings and which repositories need attention." on={on} speed={22} />
      </div>
      <Appear on={on} delay={1900} className="mt-2.5 rounded-sm border border-white/[0.06] p-2.5">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <Mail className="size-3.5" />
          <span className="truncate">Sent to 4 recipients</span>
        </div>
        <p className="mt-1.5 font-medium text-foreground/90">acme/web needs attention</p>
        <ul className="mt-1 space-y-1 text-[11px] text-muted-foreground">
          <li className="flex gap-1.5">
            <span className="text-faint">•</span>
            <span className="truncate">2 critical security findings still open</span>
          </li>
          <li className="flex gap-1.5">
            <span className="text-faint">•</span>
            <span className="truncate">acme/api is clean after 9 reviews</span>
          </li>
        </ul>
      </Appear>
    </div>
  );
}

/* -------------------------------------------------------------- analytics */

const DAYS: [number, number, number][] = [
  [3, 0, 1], [4, 1, 0], [2, 0, 0], [5, 0, 1], [6, 1, 0], [4, 0, 0], [1, 0, 0],
  [5, 0, 1], [7, 1, 0], [6, 0, 1], [8, 0, 0], [5, 1, 0], [2, 0, 0], [7, 0, 1],
];

export function AnalyticsMock() {
  const [ref, on] = useInView<HTMLDivElement>(0.4, true);
  const max = 10;
  return (
    <div ref={ref} className={cn(MOCK, "p-3")}>
      <div className="grid grid-cols-3 gap-2">
        {[
          { k: "Reviews", v: 77, sub: "past 14 days" },
          { k: "Findings", v: 142, sub: "9 critical" },
          { k: "First review", v: 2, sub: "median, min" },
        ].map((m, i) => (
          <div key={m.k} className="rounded-sm border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
            <div className="truncate text-[10.5px] text-muted-foreground">{m.k}</div>
            <div className="text-[17px] leading-6 font-medium tracking-tight text-foreground">
              <CountUp to={m.v} on={on} delay={i * 120} />
            </div>
            <div className="truncate text-[10px] text-faint">{m.sub}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between px-0.5 text-[10.5px] text-muted-foreground">
        <span>Reviews (per day)</span>
        <span className="flex gap-2.5">
          {[
            ["bg-[#46e1a5]", "Completed"],
            ["bg-[#ff6467]", "Blocked"],
            ["bg-faint", "Other"],
          ].map(([c, l]) => (
            <span key={l} className="flex items-center gap-1">
              <span className={cn("size-1.5 rounded-[1px]", c)} />
              {l}
            </span>
          ))}
        </span>
      </div>
      <div className="relative mt-2 h-[84px] border-b border-white/[0.08]">
        {[0.33, 0.66].map((y) => (
          <div key={y} className="absolute inset-x-0 border-t border-dashed border-white/[0.05]" style={{ top: `${y * 100}%` }} />
        ))}
        <div className="absolute inset-0 flex items-end gap-[4px] px-0.5">
          {DAYS.map(([c, b, o], i) => {
            const total = c + b + o;
            const style: CSSProperties = {
              height: on ? `${(total / max) * 100}%` : "0%",
              transitionDelay: `${i * 45}ms`,
            };
            return (
              <div key={i} className="flex flex-1 flex-col justify-end overflow-hidden rounded-t-[2px] transition-[height] duration-700 ease-out" style={style}>
                {o ? <div className="bg-faint/70" style={{ flexGrow: o }} /> : null}
                {b ? <div className="bg-[#ff6467]" style={{ flexGrow: b }} /> : null}
                <div className="bg-[#46e1a5]" style={{ flexGrow: c }} />
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-2.5 space-y-1.5">
        {[
          ["Critical", 18, "bg-[#ff6467]"],
          ["Major", 46, "bg-[#ffc53d]"],
          ["Minor", 36, "bg-[#687ff5]"],
        ].map(([label, pct, c], i) => (
          <div key={label as string} className="flex items-center gap-2 text-[10.5px]">
            <span className="w-11 text-muted-foreground">{label}</span>
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/[0.05]">
              <div
                className={cn("h-full rounded-full transition-[width] duration-1000 ease-out", c as string)}
                style={{ width: on ? `${pct}%` : "0%", transitionDelay: `${500 + i * 120}ms` }}
              />
            </div>
            <span className="w-7 text-right font-mono text-faint">{pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- ledger */

const LEDGER: { date: string; type: string; tone: Tone; change: string; balance: number }[] = [
  { date: "Sep 30, 10:42", type: "Review settled", tone: "neutral", change: "+185", balance: 635 },
  { date: "Sep 30, 10:39", type: "Reserved for review", tone: "amber", change: "−300", balance: 450 },
  { date: "Sep 29, 18:05", type: "Credit pack", tone: "violet", change: "+500", balance: 750 },
  { date: "Sep 29, 17:51", type: "Chat reply", tone: "neutral", change: "−50", balance: 250 },
  { date: "Sep 29, 17:20", type: "Refund", tone: "mint", change: "+200", balance: 300 },
  { date: "Sep 29, 17:14", type: "Reserved for review", tone: "amber", change: "−200", balance: 100 },
  { date: "Sep 29, 17:02", type: "Signup bonus", tone: "mint", change: "+300", balance: 300 },
];

export function LedgerMock() {
  const [ref, on] = useInView<HTMLDivElement>(0.4, true);
  return (
    <div ref={ref} className={cn(MOCK, "overflow-hidden")}>
      <div className="flex items-end justify-between gap-4 border-b border-white/[0.06] px-3 py-2.5">
        <div>
          <div className="font-mono text-[10px] tracking-wide text-faint uppercase">Balance</div>
          <div className="text-[20px] leading-7 font-medium tracking-tight text-foreground">
            <CountUp to={635} on={on} /> <span className="text-[12px] font-normal text-muted-foreground">credits</span>
          </div>
        </div>
        <span className="pb-1 text-[10.5px] text-faint">Billed by actual AI usage</span>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-3 border-b border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-[10.5px] text-muted-foreground sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
        <span className="hidden sm:block">Date</span>
        <span>Type</span>
        <span className="w-9 text-right">Change</span>
        <span className="w-11 text-right">Balance</span>
      </div>
      <ul className="divide-y divide-white/[0.05]">
        {LEDGER.map((r, i) => (
          <li key={r.date + r.type}>
            <Appear
              on={on}
              delay={200 + i * 110}
              className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-3 px-3 py-[6px] sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]"
            >
              <span className="hidden truncate text-foreground/75 sm:block">{r.date}</span>
              <span>
                <Chip tone={r.tone}>{r.type}</Chip>
              </span>
              <span
                className={cn(
                  "w-9 text-right font-mono text-[11px]",
                  r.change.startsWith("+") ? "text-[#46e1a5]" : r.change === "0" ? "text-[#46e1a5]/70" : "text-[#ff8a8c]",
                )}
              >
                {r.change}
              </span>
              <span className="w-11 text-right font-mono text-[11px] text-foreground/80">{r.balance}</span>
            </Appear>
          </li>
        ))}
      </ul>
    </div>
  );
}
