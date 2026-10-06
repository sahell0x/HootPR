import {
  Check,
  ChevronDown,
  ChevronRight,
  GitCommitHorizontal,
  ListTree,
  TriangleAlert,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import {
  MockBar,
  OwlAvatar,
  Sev,
  StatusPill,
  Tag,
  Tick,
  UserAvatar,
} from "./b-frame";

const N = 5;

function Comment({
  avatar,
  name,
  badge,
  meta,
  children,
  delay = 0,
}: {
  avatar: ReactNode;
  name: string;
  badge: string;
  meta: string;
  children: ReactNode;
  delay?: number;
}) {
  return (
    <div className="b-in flex gap-3" style={{ animationDelay: `${delay}ms` }}>
      <span className="hidden sm:block">{avatar}</span>
      <div className="min-w-0 flex-1 overflow-hidden rounded-md border border-[#2e2a31] bg-[#1c191f]">
        <div className="flex items-center gap-2 border-b border-[#2a262d] bg-[#201d23] px-3 py-1.5 text-[11.5px]">
          <span className="font-semibold text-[#efedf0]">{name}</span>
          <Tag>{badge}</Tag>
          <span className="truncate text-[#8f8a96]">{meta}</span>
        </div>
        <div className="px-3 py-2.5 text-[12.5px] leading-[1.5] text-[#d9d6dc]">
          {children}
        </div>
      </div>
    </div>
  );
}

function Code({
  n,
  text,
  kind,
  glow,
  delay = 0,
}: {
  n: number | string;
  text: string;
  kind?: "add" | "del";
  glow?: boolean;
  delay?: number;
}) {
  return (
    <div
      className={cn(
        "flex font-mono text-[11px] leading-[20px]",
        kind === "add" && "bg-[#0f3a26]",
        kind === "del" && "bg-[#4a1520]",
        glow && "b-glow shadow-[inset_2px_0_0_#ff8a3d]",
      )}
      style={glow ? { animationDelay: `${delay}ms` } : undefined}
    >
      <span className="w-9 shrink-0 pr-2 text-right text-[#5f5a66] select-none">
        {n}
      </span>
      <span className="w-3 shrink-0 text-[#5f5a66]">
        {kind === "add" ? "+" : kind === "del" ? "-" : " "}
      </span>
      <span
        className={cn(
          "truncate whitespace-pre",
          kind === "add"
            ? "text-[#7ef0b8]"
            : kind === "del"
              ? "text-[#ff9aa6]"
              : "text-[#bdb8c2]",
        )}
      >
        {text}
      </span>
    </div>
  );
}

const Mention = ({ children }: { children: ReactNode }) => (
  <span className="font-medium text-[#ff8a3d]">{children}</span>
);
const C = ({ children }: { children: ReactNode }) => (
  <code className="rounded bg-[#2a262d] px-1 font-mono text-[11px]">
    {children}
  </code>
);

/* Slide 0: inline finding in HootPR's real comment format, anchored to the diff. */
function InlineFinding() {
  return (
    <div className="space-y-3">
      <div className="b-in overflow-hidden rounded-md border border-[#2e2a31]">
        <div className="flex items-center justify-between border-b border-[#2a262d] bg-[#1d1a20] px-3 py-1.5 font-mono text-[11px] text-[#a9a4ae]">
          <span>src/billing/plans.ts</span>
          <span>
            <span className="text-[#7ef0b8]">+12</span>{" "}
            <span className="text-[#ff9aa6]">-4</span>
          </span>
        </div>
        <div className="bg-[#18151a] py-1">
          <Code
            n={40}
            text="export async function changePlan(orgId: string, input: PlanInput) {"
          />
          <Code
            n={41}
            text="  const current = await cache.get(`plan:${orgId}`);"
          />
          <Code
            n={42}
            text="  await db.plan.update({ where: { orgId }, data: input });"
            glow
            delay={250}
          />
          <Code
            n={43}
            text="  return { ...current, ...input };"
            glow
            delay={400}
          />
          <Code n={44} text="}" />
        </div>
      </div>
      <div className="pl-3 sm:pl-9">
        <Comment
          avatar={<OwlAvatar />}
          name="hootpr"
          badge="bot"
          meta="reviewed 2m ago"
          delay={500}
        >
          <p className="text-[11.5px] text-[#a9a4ae] italic">
            ⚠️ Potential issue |{" "}
            <span className="text-[#ff8a3d]">🟠 Major</span>
          </p>
          <p className="mt-1.5 text-[13px] font-semibold text-[#efedf0]">
            Cached plan is never invalidated after the update.
          </p>
          <p className="mt-1 text-[#b5b2b9]">
            The row changes, but <C>plan:{"{orgId}"}</C> stays in Redis for 10
            minutes, so limits are enforced against the old plan until it
            expires.
          </p>
          <div
            className="b-in mt-2.5 overflow-hidden rounded border border-[#2e2a31]"
            style={{ animationDelay: "800ms" }}
          >
            <div className="border-b border-[#2a262d] bg-[#201d23] px-2 py-1 text-[10.5px] text-[#8f8a96]">
              Suggested change
            </div>
            <Code
              n={42}
              text="  await db.plan.update({ where: { orgId }, data: input });"
              kind="del"
            />
            <Code n={43} text="  return { ...current, ...input };" kind="del" />
            <Code
              n={42}
              text="  await updatePlanAndInvalidate(orgId, input);"
              kind="add"
            />
            <Code n={43} text="  return getPlan(orgId);" kind="add" />
          </div>
          <p className="mt-2 flex items-center gap-1 text-[11.5px] text-[#a9a4ae]">
            <ChevronRight className="size-3" /> 🤖 Prompt for AI Agents
          </p>
          <div className="mt-2 flex items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded bg-[#2a262d] px-2 py-1 text-[11px] text-[#efedf0]">
              <GitCommitHorizontal className="size-3" /> Commit suggestion
            </span>
            <span className="text-[11px] text-[#6f6b75]">
              Resolve conversation
            </span>
          </div>
        </Comment>
      </div>
    </div>
  );
}

/* Slide 1: the review Trace timeline from the HootPR dashboard, ending with the judge. */
const STAGES: [string, string, number, string][] = [
  ["config", "source: .hootpr.yaml", 4, "0.9 s"],
  ["diff", "6 of 6 files reviewable", 3, "612 ms"],
  ["sandbox", "network sealed", 9, "2.4 s"],
  ["graph", "14 symbols, scope full", 4, "301 ms"],
  ["tools", "4 findings from eslint, semgrep, gitleaks", 70, "28.1 s"],
  ["context", "2 guideline files, 3 learnings", 3, "57 ms"],
  ["agents", "4 tasks, 11 candidate findings", 46, "19.6 s"],
  ["judge", "11 candidates → 3 inline, 1 additional", 18, "6.2 s"],
  ["post", "3 inline, walkthrough updated", 12, "4.9 s"],
];

function Trace() {
  return (
    <div className="space-y-3">
      <div className="b-in rounded-md border border-[#2e2a31] bg-[#1a171d] p-3">
        <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[#efedf0]">
          <ListTree className="size-3.5" /> Review summary{" "}
          <span className="ml-auto">
            <StatusPill>Completed</StatusPill>
          </span>
        </p>
        <p className="mt-1.5 text-[11.5px] text-[#b5b2b9]">
          <span className="font-semibold text-[#efedf0]">Findings</span> —{" "}
          <Tick to={11} /> candidates: 3 posted inline, 1 in the walkthrough,{" "}
          <span className="text-[#85f9c5]">
            <Tick to={7} /> dropped or merged by the judge
          </span>
        </p>
      </div>
      <div
        className="b-in rounded-md border border-[#2e2a31] bg-[#1a171d]"
        style={{ animationDelay: "120ms" }}
      >
        <div className="flex items-center justify-between border-b border-[#2a262d] px-3 py-2">
          <span className="text-[12.5px] font-semibold text-[#efedf0]">
            Timeline
          </span>
          <span className="font-mono text-[10.5px] text-[#6f6b75]">
            13 stages
          </span>
        </div>
        <div className="space-y-[7px] px-3 py-2.5">
          {STAGES.map(([name, note, pct, t], i) => {
            const judge = name === "judge";
            return (
              <div
                key={name}
                className={cn(
                  "b-in grid grid-cols-[14px_62px_1fr_46px] items-start gap-2",
                  judge && "-mx-1.5 rounded bg-[#46e1a5]/[.07] px-1.5 py-1",
                )}
                style={{ animationDelay: `${200 + i * 110}ms` }}
              >
                <span className="mt-[3px] size-2.5 rounded-full border-2 border-[#46e1a5]/80" />
                <span className="font-mono text-[11px] text-[#efedf0]">
                  {name}
                </span>
                <span className="min-w-0">
                  <span className="block h-[3px] rounded-full bg-[#2a262d]">
                    <span
                      className="b-grow block h-full rounded-full bg-[#46e1a5]/80"
                      style={{
                        width: `${pct}%`,
                        animationDelay: `${300 + i * 110}ms`,
                      }}
                    />
                  </span>
                  <span
                    className={cn(
                      "mt-1 block truncate text-[10.5px]",
                      judge ? "text-[#85f9c5]" : "text-[#8f8a96]",
                    )}
                  >
                    {note}
                  </span>
                </span>
                <span className="text-right font-mono text-[10.5px] text-[#a9a4ae]">
                  {t}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* Slide 2: teach it a convention by replying; the real "✏️ Learnings added" block. */
function Learning() {
  return (
    <div className="space-y-3">
      <Comment
        avatar={<OwlAvatar />}
        name="hootpr"
        badge="bot"
        meta="reviewed 6m ago"
      >
        <p className="text-[11.5px] text-[#a9a4ae] italic">
          🛠️ Refactor suggestion |{" "}
          <span className="text-[#ffc53d]">🟡 Minor</span>
        </p>
        <p className="mt-1 font-semibold text-[#efedf0]">
          Map PlanNotFound to a 404 in the service.
        </p>
      </Comment>
      <Comment
        avatar={<UserAvatar initials="MR" color="#5b6bd6" />}
        name="maya-r"
        badge="author"
        meta="replied 3m ago"
        delay={200}
      >
        <Mention>@hootpr</Mention> In this repo the route handlers own HTTP
        mapping. Services only throw domain errors.
      </Comment>
      <Comment
        avatar={<OwlAvatar />}
        name="hootpr"
        badge="bot"
        meta="replied now"
        delay={450}
      >
        <p className="text-[#efedf0]">
          <Mention>@maya-r</Mention> Got it. I&apos;ll follow that convention in
          future reviews of this repository.
        </p>
        <div className="mt-2.5 border-t border-[#2a262d] pt-2.5">
          <p className="flex items-center gap-1 text-[11.5px] font-semibold text-[#d9d6dc]">
            <ChevronDown className="size-3.5" /> ✏️ Learnings added
          </p>
          <div
            className="b-wipe mt-2 rounded bg-[#131015] px-3 py-2.5 font-mono text-[11px] leading-[1.7] text-[#bdb8c2]"
            style={{ animationDelay: "750ms" }}
          >
            <div>Learnt from: maya-r</div>
            <div>PR: acme/web#214</div>
            <div>File: src/api/plans/route.ts:18-31</div>
            <div className="text-[#6f6b75]">
              Timestamp: 2026-09-30T11:42:07Z
            </div>
            <div className="mt-1.5 text-[#7ef0b8]">
              Learning: Services throw domain errors; route handlers map them to
              HTTP responses.
            </div>
          </div>
        </div>
      </Comment>
    </div>
  );
}

/* Slide 3: chat with @hootpr in the thread. */
function Chat() {
  return (
    <div className="space-y-3">
      <Comment
        avatar={<UserAvatar initials="JL" color="#2f8f6b" />}
        name="jon-l"
        badge="reviewer"
        meta="commented 1m ago"
      >
        <Mention>@hootpr</Mention> is <C>changePlan</C> called anywhere outside
        the billing module? Want to know the blast radius.
      </Comment>
      <Comment
        avatar={<OwlAvatar />}
        name="hootpr"
        badge="bot"
        meta="replied now"
        delay={250}
      >
        <p className="text-[#efedf0]">
          <Mention>@jon-l</Mention> Yes, from 3 call sites. Two are safe; one
          reads the cached plan right after:
        </p>
        <ul className="mt-2 space-y-1 font-mono text-[11px]">
          {[
            ["src/api/orgs/upgrade.ts:31", "ok", "#46e1a5"],
            ["src/jobs/trial-expiry.ts:58", "ok", "#46e1a5"],
            ["src/api/limits/check.ts:17", "reads plan:{orgId}", "#ffc53d"],
          ].map(([f, s, c], i) => (
            <li
              key={f}
              className="b-in flex items-center gap-2"
              style={{ animationDelay: `${550 + i * 160}ms` }}
            >
              {c === "#46e1a5" ? (
                <Check className="size-3 text-[#46e1a5]" />
              ) : (
                <TriangleAlert className="size-3 text-[#ffc53d]" />
              )}
              <span className="truncate text-[#d9d6dc]">{f}</span>
              <span className="shrink-0" style={{ color: c }}>
                {s}
              </span>
            </li>
          ))}
        </ul>
        <p
          className="b-in mt-2 text-[#b5b2b9]"
          style={{ animationDelay: "1100ms" }}
        >
          The suggested fix covers the third one. Want unit tests for{" "}
          <C>updatePlanAndInvalidate</C>?
        </p>
      </Comment>
      <Comment
        avatar={<UserAvatar initials="JL" color="#2f8f6b" />}
        name="jon-l"
        badge="reviewer"
        meta="just now"
        delay={1500}
      >
        <Mention>@hootpr</Mention>{" "}
        <span
          className="b-type inline-block align-bottom"
          style={{ animationDelay: "1800ms" }}
        >
          generate unit tests
        </span>
        <span className="b-pulse ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 bg-[#efedf0]" />
      </Comment>
    </div>
  );
}

/* Slide 4: .hootpr.yaml (keys from the real config schema). */
function Config() {
  const k = "text-[#8b9cf6]";
  const s = "text-[#7ef0b8]";
  const b = "text-[#ff8a3d]";
  const lines: ReactNode[] = [
    <span className="text-[#6f6b75]" key="c">
      # .hootpr.yaml
    </span>,
    <>
      <span className={k}>reviews</span>:
    </>,
    <>
      {" "}
      <span className={k}>profile</span>: <span className={s}>assertive</span>
    </>,
    <>
      {" "}
      <span className={k}>path_instructions</span>:
    </>,
    <>
      {" "}
      - <span className={k}>path</span>:{" "}
      <span className={s}>&quot;src/api/**&quot;</span>
    </>,
    <>
      {" "}
      <span className={k}>instructions</span>:{" "}
      <span className={s}>&quot;Handlers map domain errors to HTTP.&quot;</span>
    </>,
    <>
      {" "}
      - <span className={k}>path</span>:{" "}
      <span className={s}>&quot;**/*.sql&quot;</span>
    </>,
    <>
      {" "}
      <span className={k}>instructions</span>:{" "}
      <span className={s}>&quot;Flag missing indexes on new FKs.&quot;</span>
    </>,
    <>
      {" "}
      <span className={k}>pre_merge_checks</span>:
    </>,
    <>
      {" "}
      <span className={k}>title</span>: {"{ "}
      <span className={k}>mode</span>: <span className={s}>error</span>
      {" }"}
    </>,
    <>
      {" "}
      <span className={k}>tools</span>:
    </>,
    <>
      {" "}
      <span className={k}>semgrep</span>: {"{ "}
      <span className={k}>enabled</span>: <span className={b}>true</span>
      {" }"}
    </>,
    <>
      {" "}
      <span className={k}>gitleaks</span>: {"{ "}
      <span className={k}>enabled</span>: <span className={b}>true</span>
      {" }"}
    </>,
    <>
      {" "}
      <span className={k}>ast_grep</span>:
    </>,
    <>
      {" "}
      <span className={k}>rule_dirs</span>: [
      <span className={s}>&quot;.hootpr/rules&quot;</span>]
    </>,
    <>
      {" "}
      <span className={k}>finishing_touches</span>:
    </>,
    <>
      {" "}
      <span className={k}>unit_tests</span>: {"{ "}
      <span className={k}>enabled</span>: <span className={b}>true</span>
      {" }"}
    </>,
  ];
  return (
    <div className="flex gap-3">
      <div className="b-in min-w-0 flex-1 overflow-hidden rounded-md border border-[#2e2a31] bg-[#18151a]">
        <div className="flex items-center gap-2 border-b border-[#2a262d] bg-[#1d1a20] px-3 py-1.5 font-mono text-[11px] text-[#a9a4ae]">
          .hootpr.yaml <span className="text-[#6f6b75]">· repo root</span>
        </div>
        <div className="py-2">
          {lines.map((l, i) => (
            <div
              key={i}
              className="b-in flex font-mono text-[11px] leading-[19px] whitespace-pre"
              style={{ animationDelay: `${i * 45}ms` }}
            >
              <span className="w-8 shrink-0 pr-2 text-right text-[#5f5a66] select-none">
                {i + 1}
              </span>
              <span className="truncate text-[#d9d6dc]">{l}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="hidden w-[190px] shrink-0 space-y-2 md:block">
        {[
          ["Organization defaults", "inherited", false],
          ["Repository file", "overrides 6 keys", true],
          ["Schema", "valid", true],
        ].map(([t, v, ok], i) => (
          <div
            key={t as string}
            className="b-pop rounded-md border border-[#2e2a31] bg-[#1c191f] px-3 py-2"
            style={{ animationDelay: `${500 + i * 160}ms` }}
          >
            <div className="text-[10.5px] text-[#8f8a96]">{t}</div>
            <div
              className={cn(
                "mt-0.5 flex items-center gap-1 text-[12px] font-medium",
                ok ? "text-[#85f9c5]" : "text-[#a9a4ae]",
              )}
            >
              {ok ? <Check className="size-3" /> : null} {v}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const SLIDES = [InlineFinding, Trace, Learning, Chat, Config];

export function ReviewMock({ active }: { active: number }) {
  const Slide = SLIDES[active] ?? InlineFinding;
  return (
    <div className="flex h-full flex-col">
      <MockBar
        left={
          <>
            <span className="text-[#efedf0]">acme/web</span>
            <span>#214</span>
            <span className="hidden truncate text-[#6f6b75] sm:inline">
              · fix(billing): apply plan changes immediately
            </span>
          </>
        }
        right={
          <span className="flex items-center gap-2">
            <Sev level="major" suffix=" · 1" />
            {`${active + 1}/${N}`}
          </span>
        }
      />
      <div className="relative flex-1 overflow-hidden">
        <div
          key={active}
          className="relative px-3 py-4 sm:px-6 lg:px-8 lg:py-6"
        >
          <div className="mx-auto max-w-[680px]">
            <Slide />
          </div>
        </div>
      </div>
    </div>
  );
}
