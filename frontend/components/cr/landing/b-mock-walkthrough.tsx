import { Check, CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { MockBar, OwlAvatar, Tag } from "./b-frame";

/** Offsets (px) the comment scrolls to for each slide on desktop. */
const SCROLL = [0, 70, 250, 330, 330];

function Block({
  on,
  children,
  className,
}: {
  on: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md transition-all duration-500",
        on
          ? "bg-[#221e26] opacity-100 shadow-[0_0_0_1px_#ff570a66,0_0_24px_-6px_#ff570a55]"
          : "opacity-70",
        className,
      )}
    >
      {children}
    </div>
  );
}

function Diagram({ on }: { on: boolean }) {
  const cols = [
    { x: 40, label: "Client" },
    { x: 180, label: "PlansRoute" },
    { x: 330, label: "PlanService" },
    { x: 480, label: "Redis" },
  ];
  const msgs = [
    { y: 58, a: 0, b: 1, t: "POST /plans/change" },
    { y: 84, a: 1, b: 2, t: "changePlan(orgId, input)" },
    { y: 110, a: 2, b: 3, t: "DEL plan:{orgId}" },
    { y: 136, a: 2, b: 1, t: "Plan", dash: true },
    { y: 162, a: 1, b: 0, t: "200 OK", dash: true },
  ];
  return (
    <svg
      viewBox="0 0 540 180"
      className="h-auto w-full"
      key={on ? "on" : "off"}
    >
      {cols.map((c) => (
        <g key={c.label}>
          <rect
            x={c.x - 44}
            y={8}
            width={88}
            height={24}
            rx={4}
            fill="#1f1b23"
            stroke="#3a3640"
          />
          <text
            x={c.x}
            y={24}
            textAnchor="middle"
            fontSize="10.5"
            fill="#d9d6dc"
            fontFamily="var(--font-code), monospace"
          >
            {c.label}
          </text>
          <line
            x1={c.x}
            y1={32}
            x2={c.x}
            y2={176}
            stroke="#34303a"
            strokeDasharray="3 3"
          />
        </g>
      ))}
      {msgs.map((m, i) => {
        const x1 = cols[m.a]?.x ?? 0;
        const x2 = cols[m.b]?.x ?? 0;
        const dir = x2 > x1 ? 1 : -1;
        const len = Math.abs(x2 - x1);
        return (
          <g key={m.t}>
            <line
              x1={x1}
              y1={m.y}
              x2={x2 - dir * 4}
              y2={m.y}
              stroke={m.dash ? "#8f8a96" : "#ff8a3d"}
              strokeWidth={1.2}
              strokeDasharray={m.dash ? "4 3" : undefined}
              className={on && !m.dash ? "b-draw" : undefined}
              style={
                on && !m.dash
                  ? ({
                      "--b-len": len,
                      animationDelay: `${i * 220}ms`,
                    } as CSSProperties)
                  : undefined
              }
            />
            <path
              d={`M${x2} ${m.y} l${-dir * 6} -3.5 v7 z`}
              fill={m.dash ? "#8f8a96" : "#ff8a3d"}
            />
            <text
              x={(x1 + x2) / 2}
              y={m.y - 5}
              textAnchor="middle"
              fontSize="9.5"
              fill="#b5b2b9"
              fontFamily="var(--font-code), monospace"
            >
              {m.t}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function WalkthroughMock({ active }: { active: number }) {
  const rows = [
    [
      "src/billing/plans.ts",
      "changePlan now invalidates the cached plan and returns fresh data.",
    ],
    [
      "src/billing/cache.ts",
      "New updatePlanAndInvalidate helper wraps update + DEL in one call.",
    ],
    [
      "src/api/limits/check.ts",
      "Reads the plan through getPlan instead of the raw cache key.",
    ],
    [
      "tests/billing/plans.test.ts",
      "Covers upgrade, downgrade and stale-cache regression.",
    ],
  ];
  return (
    <div className="flex h-full flex-col">
      <MockBar
        left={
          <>
            <span className="text-[#efedf0]">acme/web</span>
            <span>#214</span>
            <span className="hidden text-[#6f6b75] sm:inline">
              · Conversation
            </span>
          </>
        }
        right={
          <span className="inline-flex items-center gap-1.5 text-[#7ef0b8]">
            <CheckCircle2 className="size-3.5" /> HootPR · passed
          </span>
        }
      />
      <div className="relative flex-1 overflow-hidden">
        <div
          className="px-3 py-4 transition-transform duration-700 ease-[cubic-bezier(.3,.7,.2,1)] sm:px-6 lg:px-8 lg:py-6"
          style={{ transform: `translateY(-${SCROLL[active] ?? 0}px)` }}
        >
          <div className="mx-auto flex max-w-[700px] gap-3">
            <OwlAvatar className="hidden sm:grid" />
            <div className="min-w-0 flex-1 overflow-hidden rounded-md border border-[#2e2a31] bg-[#1c191f]">
              <div className="flex items-center gap-2 border-b border-[#2a262d] bg-[#201d23] px-3 py-1.5 text-[11.5px]">
                <span className="font-semibold text-[#efedf0]">hootpr</span>
                <Tag>bot</Tag>
                <span className="text-[#8f8a96]">
                  commented 4m ago · edited
                </span>
              </div>
              <div className="space-y-3 p-3 text-[12.5px] leading-[1.5]">
                <Block on={active === 0} className="p-2.5">
                  <p className="text-[15px] font-semibold text-[#efedf0]">
                    Walkthrough
                  </p>
                  <p
                    className={cn(
                      "mt-1 text-[#b5b2b9]",
                      active === 0 && "b-wipe",
                    )}
                  >
                    Plan changes now take effect immediately. The service clears
                    the cached plan after the database write, and the limits
                    check reads through{" "}
                    <code className="rounded bg-[#2a262d] px-1 font-mono text-[11px]">
                      getPlan
                    </code>{" "}
                    so it never sees a stale tier.
                  </p>
                </Block>

                <Block on={active === 1} className="p-2.5">
                  <p className="text-[15px] font-semibold text-[#efedf0]">
                    Changes
                  </p>
                  <div className="mt-2 overflow-hidden rounded border border-[#2e2a31]">
                    <div className="grid grid-cols-[minmax(0,.9fr)_minmax(0,1.6fr)] bg-[#201d23] px-2.5 py-1.5 text-[11px] font-semibold text-[#a9a4ae]">
                      <span>Cohort / File(s)</span>
                      <span>Summary</span>
                    </div>
                    {rows.map(([f, s], i) => (
                      <div
                        key={f}
                        className={cn(
                          "grid grid-cols-[minmax(0,.9fr)_minmax(0,1.6fr)] gap-3 border-t border-[#2a262d] px-2.5 py-1.5",
                          active === 1 && "b-in",
                        )}
                        style={{ animationDelay: `${i * 90}ms` }}
                      >
                        <span className="truncate font-mono text-[11px] text-[#8b9cf6]">
                          {f}
                        </span>
                        <span className="text-[11.5px] text-[#bdb8c2]">
                          {s}
                        </span>
                      </div>
                    ))}
                  </div>
                </Block>

                <Block on={active === 2} className="p-2.5">
                  <p className="text-[15px] font-semibold text-[#efedf0]">
                    Sequence Diagram(s)
                  </p>
                  <div className="mt-2 rounded border border-[#2e2a31] bg-[#151217] p-2">
                    <Diagram on={active === 2} />
                  </div>
                </Block>

                <div className="grid gap-3 sm:grid-cols-2">
                  <Block on={active === 3} className="p-2.5">
                    <p className="text-[13px] font-semibold text-[#efedf0]">
                      Estimated code review effort
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      <div className="flex gap-1">
                        {[0, 1, 2, 3, 4].map((i) => (
                          <span
                            key={i}
                            className="h-2 w-5 rounded-sm transition-colors duration-500"
                            style={{
                              background:
                                i < 3
                                  ? active === 3
                                    ? "#ffc53d"
                                    : "#8a6f2a"
                                  : "#2e2a31",
                              transitionDelay: `${i * 120}ms`,
                            }}
                          />
                        ))}
                      </div>
                      <span className="font-mono text-[11px] text-[#8f8a96]">
                        3 / 5
                      </span>
                    </div>
                    <p className="mt-1.5 flex items-center gap-1 text-[11.5px] text-[#b5b2b9]">
                      🎯 3 (Moderate) <span className="text-[#5f5a66]">|</span>{" "}
                      ⏱️ ~25 minutes
                    </p>
                  </Block>
                  <Block on={active === 4} className="p-2.5">
                    <p className="text-[13px] font-semibold text-[#efedf0]">
                      Pre-merge checks
                    </p>
                    <p className="mt-1 flex items-center gap-1 text-[11.5px] text-[#d9d6dc]">
                      <ChevronDown className="size-3" /> ✅ Passed checks (3
                      passed)
                    </p>
                    <ul className="mt-1 space-y-1 text-[11px]">
                      {[
                        "Title check",
                        "Description check",
                        "Docstring coverage",
                      ].map((t, i) => (
                        <li
                          key={t}
                          className={cn(
                            "flex items-center gap-1.5 text-[#bdb8c2]",
                            active === 4 && "b-in",
                          )}
                          style={{ animationDelay: `${200 + i * 180}ms` }}
                        >
                          <Check className="size-3 text-[#46e1a5]" /> {t}
                          <span className="ml-auto text-[#85f9c5]">Passed</span>
                        </li>
                      ))}
                    </ul>
                  </Block>
                </div>

                <div className="space-y-1 px-2.5 text-[11.5px] text-[#a9a4ae]">
                  <p className="flex items-center gap-1">
                    <ChevronRight className="size-3" /> 🧹 Additional comments
                    (1)
                  </p>
                  <p className="flex items-center gap-1">
                    <ChevronRight className="size-3" /> 📜 Review details
                  </p>
                </div>

                <Block
                  on={active === 4}
                  className="border border-[#2e2a31] p-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="size-4 text-[#46e1a5]" />
                      <div>
                        <p className="text-[12px] font-semibold text-[#efedf0]">
                          HootPR{" "}
                          <span className="font-normal text-[#8f8a96]">
                            — Review completed
                          </span>
                        </p>
                        <p className="text-[11px] text-[#8f8a96]">
                          Required · 3 actionable comments
                        </p>
                      </div>
                    </div>
                    <span className="rounded bg-[#1f7a52] px-2 py-1 text-[11px] font-medium text-white">
                      Merge pull request
                    </span>
                  </div>
                </Block>
              </div>
            </div>
          </div>
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-[#161318] to-transparent" />
      </div>
    </div>
  );
}
