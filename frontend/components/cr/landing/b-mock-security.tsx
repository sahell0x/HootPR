import {
  BookOpen,
  Building2,
  ChevronDown,
  FileText,
  FolderGit2,
  GitPullRequest,
  Layers,
  LayoutGrid,
  Radar,
  ScanSearch,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { OwlAvatar, Tick } from "./b-frame";

/* Attack-surface strip per repo: each cell is an HTTP endpoint.
   g = auth check found, a = public by design / exposure, r = no auth check, e = empty. */
const REPOS: { name: string; eps: number; cells: string }[] = [
  {
    name: "acme/web",
    eps: 41,
    cells: "gggggggggggggrggggggggggaggggggggggggggggg",
  },
  {
    name: "acme/api",
    eps: 38,
    cells: "ggggggggggggggggggggrgggggggggggggggggaaee",
  },
  {
    name: "acme/auth",
    eps: 14,
    cells: "ggggggggrgggggeeeeeeeeeeeeeeeeeeeeeeeeeee",
  },
  {
    name: "acme/billing",
    eps: 29,
    cells: "gggggggggggggggggggggagggrggggeeeeeeeeeee",
  },
  {
    name: "acme/workers",
    eps: 26,
    cells: "ggggggggggggggggggggggaaggeeeeeeeeeeeeeee",
  },
];
const CELL = {
  g: "#1f9e6e",
  a: "#e5a82e",
  r: "#e0445c",
  e: "#231f27",
} as const;

function series() {
  const n = 30;
  const hi: number[] = [];
  const med: number[] = [];
  const low: number[] = [];
  for (let i = 0; i < n; i++) {
    hi.push(30 + 9 * Math.sin(i / 4) - i * 0.45);
    med.push(28 + 7 * Math.sin(i / 3 + 1) + (i > 14 ? 5 : 0));
    low.push(24 + 5 * Math.cos(i / 5));
  }
  return { n, hi, med, low };
}

function Area() {
  const { n, hi, med, low } = series();
  const W = 560;
  const H = 150;
  const max = 110;
  const x = (i: number) => (i / (n - 1)) * W;
  const y = (v: number) => H - (v / max) * H;
  const path = (top: number[], base: number[]) => {
    const up = top
      .map(
        (v, i) =>
          `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v + (base[i] ?? 0)).toFixed(1)}`,
      )
      .join(" ");
    const down = base
      .map((v, i) => [i, v] as const)
      .reverse()
      .map(([i, v]) => `L${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
      .join(" ");
    return `${up} ${down} Z`;
  };
  const zero = hi.map(() => 0);
  const s2 = hi.map((v, i) => v + (med[i] ?? 0));
  const cx = x(19);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="h-full w-full"
    >
      {[0.25, 0.5, 0.75].map((f) => (
        <line
          key={f}
          x1={0}
          x2={W}
          y1={H * f}
          y2={H * f}
          stroke="#2a262d"
          strokeWidth={1}
        />
      ))}
      <g className="b-wipe" style={{ animationDuration: "1.8s" }}>
        <path d={path(low, s2)} fill="#5b5160" fillOpacity={0.9} />
        <path d={path(med, hi)} fill="#e5a82e" fillOpacity={0.92} />
        <path d={path(hi, zero)} fill="#ff570a" fillOpacity={0.95} />
      </g>
      <rect
        x={cx - 24}
        y={0}
        width={48}
        height={H}
        fill="#46e1a5"
        opacity={0.08}
      />
      <line
        x1={cx}
        x2={cx}
        y1={0}
        y2={H}
        stroke="#46e1a5"
        strokeWidth={1}
        opacity={0.6}
      />
    </svg>
  );
}

function Donut() {
  const parts = [
    { v: 8, c: "#e0445c" },
    { v: 25, c: "#ff570a" },
    { v: 42, c: "#e5a82e" },
    { v: 25, c: "#6f6b75" },
  ];
  const r = 26;
  const C = 2 * Math.PI * r;
  let acc = 0;
  return (
    <svg viewBox="0 0 70 70" className="size-[72px] -rotate-90">
      <circle
        cx={35}
        cy={35}
        r={r}
        fill="none"
        stroke="#231f27"
        strokeWidth={8}
      />
      {parts.map((p, i) => {
        const len = (p.v / 100) * C - 0.8;
        const off = acc;
        acc += (p.v / 100) * C;
        return (
          <circle
            key={p.c}
            cx={35}
            cy={35}
            r={r}
            fill="none"
            stroke={p.c}
            strokeWidth={8}
            strokeDasharray={`${len} ${C}`}
            strokeDashoffset={-off}
            className="b-draw"
            style={{
              ["--b-len" as string]: len,
              animationDelay: `${i * 180}ms`,
            }}
          />
        );
      })}
    </svg>
  );
}

function Card({
  on,
  children,
  className,
}: {
  on?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border bg-[#18151a] transition-[border-color,box-shadow] duration-500",
        on
          ? "border-[#ff8a3d80] shadow-[0_0_30px_-12px_#ff570a]"
          : "border-[#2a262d]",
        className,
      )}
    >
      {children}
    </div>
  );
}

const NAV: [string, typeof FolderGit2][] = [
  ["Repositories", FolderGit2],
  ["Dashboard", LayoutGrid],
  ["Reviews", GitPullRequest],
  ["Change Stack", Layers],
  ["Reports", FileText],
  ["Learnings", BookOpen],
  ["Security", ShieldCheck],
  ["Organization", Building2],
];

export function SecurityMock({ active }: { active: number }) {
  const stats: [string, number, string, string?][] = [
    ["Repositories mapped", 5, "Have an attack surface map", "5 / "],
    ["HTTP endpoints", 148, "Across mapped repositories"],
    ["Without auth", 6, "No auth check detected"],
    ["Exposure", 11, "Secrets refs + IaC findings"],
  ];
  return (
    <div className="flex h-full">
      {/* Real app sidebar */}
      <aside className="hidden w-[132px] shrink-0 flex-col border-r border-[#26232a] bg-[#0f0d11] px-1.5 py-2 md:flex">
        <div className="mb-2 flex items-center gap-1.5 px-1.5 text-[11px] font-semibold text-[#efedf0]">
          acme{" "}
          <span className="rounded border border-[#3a3640] px-1 font-mono text-[8px] text-[#8f8a96]">
            ORG
          </span>
          <ChevronDown className="ml-auto size-3 text-[#6f6b75]" />
        </div>
        {NAV.map(([t, I]) => (
          <div
            key={t}
            className={cn(
              "flex items-center gap-1.5 rounded px-1.5 py-[5px] text-[10.5px]",
              t === "Security"
                ? "bg-[#232127] font-medium text-[#efedf0]"
                : "text-[#a9a4ae]",
            )}
          >
            <I className="size-3" /> {t}
          </div>
        ))}
      </aside>

      <div className="relative min-w-0 flex-1 overflow-hidden">
        <div className="flex h-9 items-center justify-between border-b border-[#2a262d] px-3 text-[11px] sm:px-4">
          <span className="text-[#8f8a96]">
            acme <span className="px-1 text-[#5f5a66]">/</span>{" "}
            <span className="text-[#efedf0]">Security</span>
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded border px-2 py-1 text-[10.5px] font-medium transition-colors duration-500",
              active === 1
                ? "border-[#ff570a] bg-[#ff570a]/15 text-[#efedf0]"
                : "border-[#3a3640] text-[#efedf0]",
            )}
          >
            <Sparkles className="size-3 text-[#ff8a3d]" /> Run security review
          </span>
        </div>

        <div className="space-y-2.5 p-3 sm:p-4">
          <div>
            <p className="text-[16px] font-medium text-[#efedf0]">Security</p>
            <p className="mt-0.5 truncate text-[10.5px] text-[#8f8a96]">
              Attack surface maps inventory each repository&apos;s entry points,
              auth checks, outbound calls and exposure.
            </p>
          </div>

          {/* Stat tiles, real card style */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {stats.map(([t, v, sub, pre], i) => (
              <Card key={t} on={active === 0 && i < 3} className="b-in p-1">
                <p
                  className="px-1.5 pt-1 pb-1.5 text-[10.5px] font-medium text-[#efedf0]"
                  style={{ animationDelay: `${i * 80}ms` }}
                >
                  {t}
                </p>
                <div className="rounded bg-[#211e25] px-1.5 py-1.5">
                  <p
                    className={cn(
                      "text-[18px] leading-none font-medium tabular-nums",
                      i === 2 ? "text-[#ff9aa6]" : "text-[#efedf0]",
                    )}
                  >
                    {pre}
                    <Tick to={v} ms={900 + i * 150} />
                  </p>
                  <p className="mt-1 truncate text-[9.5px] text-[#8f8a96]">
                    {sub}
                  </p>
                </div>
              </Card>
            ))}
          </div>

          {/* Repositories: attack surface posture */}
          <Card on={active === 0} className="p-2.5">
            <div className="flex items-center justify-between font-mono text-[9.5px] tracking-wide">
              <span className="text-[#46e1a5]">
                ● ATTACK SURFACE · ENDPOINTS
              </span>
              <span className="hidden items-center gap-2 text-[#6f6b75] sm:flex">
                <span className="flex items-center gap-1">
                  <i className="size-1.5 rounded-[1px] bg-[#1f9e6e]" /> auth
                </span>
                <span className="flex items-center gap-1">
                  <i className="size-1.5 rounded-[1px] bg-[#e5a82e]" /> exposure
                </span>
                <span className="flex items-center gap-1">
                  <i className="size-1.5 rounded-[1px] bg-[#e0445c]" /> no auth
                </span>
              </span>
            </div>
            <div className="mt-2 space-y-[5px]">
              {REPOS.map((r, ri) => (
                <div key={r.name} className="flex items-center gap-2">
                  <span className="w-[74px] shrink-0 truncate font-mono text-[10px] text-[#bdb8c2]">
                    {r.name}
                  </span>
                  <span className="hidden w-7 shrink-0 text-right font-mono text-[9px] text-[#6f6b75] sm:block">
                    {r.eps}
                  </span>
                  <div className="grid flex-1 grid-cols-[repeat(24,minmax(0,1fr))] gap-[2px] md:grid-cols-[repeat(41,minmax(0,1fr))]">
                    {r.cells
                      .padEnd(41, "e")
                      .slice(0, 41)
                      .split("")
                      .map((c, i) => (
                        <span
                          key={i}
                          className={cn(
                            "b-in h-[10px] rounded-[1.5px]",
                            i >= 24 && "hidden md:block",
                          )}
                          style={{
                            background: CELL[c as keyof typeof CELL],
                            animationDelay: `${ri * 90 + i * 12}ms`,
                            animationDuration: ".35s",
                          }}
                        />
                      ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Trend + donut */}
          <div className="relative">
            <Card on={active === 4} className="p-2.5">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-[11px] font-semibold text-[#efedf0]">
                    Review activity
                  </p>
                  <p className="text-[9.5px] text-[#8f8a96]">
                    Completed · blocked · other · 30 days
                  </p>
                </div>
                <div className="hidden gap-1 text-[9.5px] lg:flex">
                  <span className="rounded bg-[#2a262d] px-1.5 py-0.5 text-[#efedf0]">
                    30 days
                  </span>
                  <span className="px-1 py-0.5 text-[#6f6b75]">90 days</span>
                </div>
              </div>
              <div
                key={active === 4 ? "a" : "b"}
                className="mt-1.5 h-[118px] lg:h-[132px]"
              >
                <Area />
              </div>
              <div className="mt-1 flex justify-between font-mono text-[8.5px] text-[#5f5a66]">
                {[
                  "Sep 1",
                  "Sep 6",
                  "Sep 11",
                  "Sep 16",
                  "Sep 21",
                  "Sep 26",
                  "Sep 30",
                ].map((d) => (
                  <span key={d}>{d}</span>
                ))}
              </div>
            </Card>

            <Card
              on={active === 1}
              className="absolute top-3 right-3 hidden w-[236px] bg-[#1f1b23] p-3 shadow-[0_20px_40px_-10px_rgba(0,0,0,.8)] sm:block"
            >
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-semibold text-[#efedf0]">
                  Security review
                </p>
                <span className="rounded border border-[#e5a82e]/60 px-1 text-[9px] text-[#ffc53d]">
                  Overall: medium
                </span>
              </div>
              <p className="text-[9.5px] text-[#8f8a96]">
                acme/api · prioritized risks
              </p>
              <div
                key={active === 1 ? "a" : "b"}
                className="mt-2 flex items-center gap-3"
              >
                <div className="relative">
                  <Donut />
                  <div className="absolute inset-0 grid place-items-center text-center">
                    <div>
                      <div className="text-[14px] font-semibold text-[#efedf0]">
                        <Tick to={12} />
                      </div>
                      <div className="text-[8px] text-[#8f8a96]">risks</div>
                    </div>
                  </div>
                </div>
                <div className="grid flex-1 grid-cols-2 gap-x-2 gap-y-1.5 text-[9.5px]">
                  {[
                    ["Critical", 1, "#e0445c"],
                    ["High", 3, "#ff570a"],
                    ["Medium", 5, "#e5a82e"],
                    ["Low", 3, "#8f8a96"],
                  ].map(([l, v, c]) => (
                    <div key={l as string}>
                      <div className="flex items-center gap-1 text-[#8f8a96]">
                        <span
                          className="size-1.5 rounded-full"
                          style={{ background: c as string }}
                        />
                        {l}
                      </div>
                      <div className="font-mono text-[#efedf0]">{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          </div>
        </div>

        {/* Per-slide toasts */}
        {active === 2 && (
          <Toast
            icon={
              <OwlAvatar className="size-5 rounded-[4px] [&_svg]:size-3.5" />
            }
            title="@hootpr security review"
            sub="acme/web #214 · report posted as a PR comment"
          />
        )}
        {active === 3 && (
          <Toast
            icon={<Radar className="size-4 text-[#8b7cf6]" />}
            title="Blast radius · acme/web #214"
            sub="2 HTTP endpoints changed · 1 without auth check"
          />
        )}
        {active === 4 && (
          <Toast
            icon={<ScanSearch className="size-4 text-[#46e1a5]" />}
            title="Sandbox scan finished"
            sub="semgrep · gitleaks · trivy · checkov — 0 critical"
          />
        )}
      </div>
    </div>
  );
}

function Toast({
  icon,
  title,
  sub,
}: {
  icon: ReactNode;
  title: string;
  sub: string;
}) {
  return (
    <div
      className="b-pop absolute bottom-4 left-3 z-10 flex max-w-[calc(100%-24px)] items-center gap-2.5 rounded-md border border-[#3a3640] bg-[#221e26] px-3 py-2 shadow-[0_20px_40px_-10px_rgba(0,0,0,.85)]"
      style={{ animationDelay: "300ms" }}
    >
      <span className="shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="truncate text-[11px] font-semibold text-[#efedf0]">
          {title}
        </p>
        <p className="truncate text-[10px] text-[#8f8a96]">{sub}</p>
      </div>
    </div>
  );
}
