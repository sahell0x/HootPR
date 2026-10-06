"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  GitMerge,
  Layers,
  ListChecks,
  MessageSquare,
  Paperclip,
  Pause,
  Play,
  Radar,
  ScrollText,
  Send,
  ShieldAlert,
  WandSparkles,
} from "lucide-react";
import { OwlMark } from "@/components/brand";
import {
  AppWindow,
  Counter,
  FileChip,
  FN,
  KW,
  MOCK_CSS,
  Rise,
  SeverityBadge,
  StatusChip,
  STR,
  Streamed,
} from "@/components/cr/landing/a-mock-kit";
import { cn } from "@/lib/utils";

/* The hero's product tour. Each pane mirrors a real HootPR screen (review detail, summary,
 * Change Stack, Security) with example data (acme/web). Illustrative only. */

const DURATION = 5500;

type PaneProps = { live: boolean };

function PageTitle({ title, n, children }: { title: string; n: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="truncate text-[16px] font-medium tracking-[-0.01em] text-foreground">
        {title} <span className="text-faint">{n}</span>
      </p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted-foreground">{children}</div>
    </div>
  );
}

function PageTabs({ active }: { active: string }) {
  const tabs: [string, number | null][] = [
    ["Summary", null],
    ["Findings", 3],
    ["Finishing touches", null],
    ["Trace", null],
  ];
  return (
    <div className="flex gap-4 border-b text-[12px]">
      {tabs.map(([t, c]) => (
        <span
          key={t}
          className={cn(
            "-mb-px flex items-center gap-1.5 border-b pb-2",
            t === active ? "border-primary text-foreground" : "border-transparent text-muted-foreground",
            t === "Trace" && "hidden @md:flex",
          )}
        >
          {t}
          {c ? <span className="rounded-sm bg-accent px-1 font-mono text-[10px] text-muted-foreground">{c}</span> : null}
        </span>
      ))}
    </div>
  );
}

/* ── 01 Review: the findings list on a review ─────────────────────────────── */

function ReviewPane({ live }: PaneProps) {
  return (
    <AppWindow crumbs={["acme", "Reviews", "Retry failed charges"]} nav="reviews">
      <div className="flex flex-col gap-3.5 p-4">
        <PageTitle title="Retry failed charges" n="#214">
          <StatusChip>Completed</StatusChip>
          <span className="font-mono text-foreground/85">acme/web</span>
          <span className="text-faint">· started 2m ago</span>
        </PageTitle>
        <PageTabs active="Findings" />
        <div className="overflow-hidden rounded-md border bg-card">
          <div className="flex items-center gap-0.5 border-b p-2 text-[11px]">
            {(
              [
                ["All", 3],
                ["Critical", 0],
                ["Major", 1],
                ["Minor", 2],
                ["Nitpick", 0],
              ] as const
            ).map(([l, c], i) => (
              <span key={l} className={cn("flex items-center gap-1 rounded-sm px-2 py-1", i === 0 ? "bg-accent text-foreground" : "text-muted-foreground", i > 3 && "hidden @md:flex")}>
                {l} <span className="font-mono text-[9.5px] text-faint">{c}</span>
              </span>
            ))}
          </div>
          <div className="flex items-center gap-2 border-b bg-subtle px-3.5 py-1.5 text-[11px] text-muted-foreground">
            Posted as inline comments <span className="rounded-sm border px-1 font-mono text-[9.5px]">1</span>
          </div>
          <div className="flex flex-col gap-2.5 p-3.5">
            <Rise live={live} i={0} className="flex items-start gap-2">
              <ShieldAlert className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="flex-1 text-[13px] leading-snug font-medium text-foreground">Add an idempotency key to the charge retry</span>
              <SeverityBadge sev="Major" />
            </Rise>
            <p className="min-h-[54px] text-[12px] leading-[1.55] text-muted-foreground">
              <Streamed
                live={live}
                delay={450}
                text="retry() re-sends charges.create without an idempotency key. If Stripe accepts the first call but the response times out, the customer is billed twice."
              />
            </p>
            <Rise live={live} i={1} base={200} className="flex items-center gap-2 text-[11px] text-muted-foreground">
              Evidence
              <span className="flex items-center gap-1 rounded-sm border px-1.5 font-mono text-[10.5px] leading-[18px] text-foreground/85">
                charge.ts · L42–L43 <ChevronRight className="size-3" aria-hidden />
              </span>
            </Rise>
            <Rise live={live} i={2} base={200} className="overflow-hidden rounded-sm border border-l-2 border-l-primary">
              <p className="border-b px-3 py-1 font-mono text-[9.5px] tracking-[0.08em] text-muted-foreground">SUGGESTION</p>
              <pre className="overflow-hidden px-3 py-2 font-mono text-[11px] leading-[1.6] text-foreground/90">
                {"stripe.charges.create(toCharge(order), {\n  "}
                <span className={KW}>idempotencyKey</span>
                {": "}
                <span className={STR}>{"`charge-${order.id}`"}</span>
                {",\n})"}
              </pre>
            </Rise>
            <Rise live={live} i={3} base={200} className="flex items-center justify-between">
              <span className="rounded-sm border px-1.5 text-[10.5px] leading-[18px] text-muted-foreground">correctness</span>
              <span className="font-mono text-[10.5px] text-faint">
                confidence <Counter live={live} to={97} delay={400} />%
              </span>
            </Rise>
            <Rise live={live} i={4} base={200} className="text-[11.5px] text-muted-foreground">
              <span className="font-mono text-[10.5px] text-faint">JUDGE</span> <span className="font-medium text-success">keep</span> — a network timeout is
              enough to double-charge.
            </Rise>
          </div>
          <div className="border-t p-3">
            <span className="inline-flex items-center gap-1.5 rounded-sm border border-dashed px-2.5 py-1 text-[11.5px] text-muted-foreground">
              <ChevronDown className="size-3" aria-hidden /> Show 2 findings filtered out by the judge
            </span>
          </div>
        </div>
      </div>
    </AppWindow>
  );
}

/* ── 02 Walkthrough: review summary + meta rail ───────────────────────────── */

function WalkthroughPane({ live }: PaneProps) {
  const steps: [string, string, string[]][] = [
    ["Retry card charges with backoff", "billing · 2 files", ["charge.ts", "retry.ts"]],
    ["Re-attempt failed invoices nightly", "jobs · 2 files", ["invoice-worker.ts", "cron.ts"]],
    ["Cover timeout and 5xx paths", "tests · 2 files", ["charge.spec.ts", "retry.spec.ts"]],
  ];
  const meta: [string, ReactNode][] = [
    ["Status", <StatusChip key="s">Completed</StatusChip>],
    ["Pull request", <span key="p" className="font-mono text-primary">acme/web#214</span>],
    ["Head commit", <span key="h" className="rounded-sm border px-1 font-mono text-[10.5px]">9f3c2e1</span>],
    ["Credits", <span key="c"><Counter live={live} to={96} /> <span className="text-faint">charged</span></span>],
    ["Files", <span key="f"><Counter live={live} to={6} /> <span className="text-faint">of 6</span></span>],
    ["Findings", <span key="n"><Counter live={live} to={3} /> <span className="text-faint">inline</span></span>],
    ["Duration", <span key="d" className="font-mono">1m 44s</span>],
  ];
  return (
    <AppWindow crumbs={["acme", "Reviews", "Retry failed charges"]} nav="reviews">
      <div className="grid @[620px]:grid-cols-[1fr_196px]">
        <div className="flex min-w-0 flex-col gap-3.5 p-4">
          <PageTitle title="Retry failed charges" n="#214">
            <StatusChip>Completed</StatusChip>
            <span className="font-mono text-foreground/85">acme/web</span>
          </PageTitle>
          <PageTabs active="Summary" />
          <div className="overflow-hidden rounded-md border bg-card">
            <div className="flex flex-col gap-2 p-3.5">
              <p className="flex items-center gap-2 text-[12.5px] font-medium text-foreground">
                <ScrollText className="size-3.5 text-muted-foreground" aria-hidden /> Review summary
              </p>
              {(
                [
                  ["Outcome", "Completed in 1m 44s"],
                  ["Coverage", "6 of 6 files reviewed"],
                  ["Findings", "5 candidates: 3 posted inline, 2 dropped by the judge"],
                ] as const
              ).map(([k, v], i) => (
                <Rise key={k} live={live} i={i} className="flex gap-2 text-[11.5px] leading-snug">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-faint" />
                  <span className="text-muted-foreground">
                    <span className="font-medium text-foreground">{k}</span> — {v}
                  </span>
                </Rise>
              ))}
            </div>
            <div className="flex flex-col gap-2.5 border-t p-3.5">
              <p className="flex items-center gap-2 text-[12.5px] font-medium text-foreground">
                <ListChecks className="size-3.5 text-muted-foreground" aria-hidden /> Walkthrough
              </p>
              {steps.map(([t, s, files], i) => (
                <Rise key={t} live={live} i={i} base={250} step={110} className="flex gap-3">
                  <span className="font-mono text-[10.5px] text-faint">0{i + 1}</span>
                  <span className="flex min-w-0 flex-col gap-1">
                    <span className="text-[12px] font-medium text-foreground">{t}</span>
                    <span className="text-[11px] text-muted-foreground">{s}</span>
                    <span className="flex flex-wrap gap-1">
                      {files.map((f) => (
                        <FileChip key={f}>{f}</FileChip>
                      ))}
                    </span>
                  </span>
                </Rise>
              ))}
            </div>
          </div>
        </div>
        <div className="hidden flex-col border-l bg-sidebar/60 @[620px]:flex">
          <p className="border-b px-3.5 py-2.5 text-center text-[10.5px] text-muted-foreground">Review · Sep 30</p>
          {meta.map(([k, v], i) => (
            <div key={k} className={cn("flex items-center justify-between gap-2 px-3.5 py-2 text-[11px]", (i === 3 || i === 6) && "border-t")}>
              <span className="text-muted-foreground">{k}</span>
              <span className="text-foreground">{v}</span>
            </div>
          ))}
          <div className="mt-2 px-3.5">
            <span className="flex items-center justify-center gap-1.5 rounded-sm border py-1.5 text-[11px] font-medium text-foreground">
              <ExternalLink className="size-3" aria-hidden /> Open pull request
            </span>
          </div>
        </div>
      </div>
    </AppWindow>
  );
}

/* ── 03 Change Stack: layers, diff, findings and chat ─────────────────────── */

type Code = { n: number; hit?: boolean; body: ReactNode };
const DIFF: Code[] = [
  { n: 24, body: <><span className={KW}>async function</span> <span className={FN}>create</span>(data) {"{"}</> },
  { n: 25, body: <>{"  "}<span className={KW}>const</span> tx = <span className={KW}>await</span> db.<span className={FN}>begin</span>();</> },
  { n: 26, body: <>{"  "}<span className={KW}>const</span> inv = <span className={KW}>await</span> tx.<span className={FN}>insert</span>(data);</> },
  { n: 27, hit: true, body: <>{"  "}<span className={KW}>await</span> mail.<span className={FN}>send</span>(inv);</> },
  { n: 28, hit: true, body: <>{"  "}<span className={KW}>await</span> tx.<span className={FN}>commit</span>();</> },
  { n: 29, body: <>{"  "}<span className={KW}>return</span> inv;</> },
  { n: 30, body: <>{"}"}</> },
];

function ChangeStackPane({ live }: PaneProps) {
  const layers: [string, [string, string][], boolean][] = [
    ["Invoice model and migration", [["db/invoice.ts", "+24 −0"]], false],
    ["Billing API and emails", [["api/invoices.ts", "+38 −4"], ["mailer/invoice.tsx", "+51 −0"]], true],
    ["Settings UI", [["settings/billing.tsx", "+17 −6"]], false],
  ];
  return (
    <AppWindow crumbs={["acme", "Change Stack", "Send invoice emails"]} nav="change-stack">
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-start gap-3">
          <PageTitle title="Send invoice emails" n="#221">
            <StatusChip>Open</StatusChip>
            <span>
              @maya wants to merge <span className="rounded-sm border bg-subtle px-1 font-mono text-[10.5px]">invoice-emails</span> into{" "}
              <span className="rounded-sm border bg-subtle px-1 font-mono text-[10.5px]">main</span>
            </span>
          </PageTitle>
          <span className="ml-auto hidden shrink-0 items-center gap-1 rounded-sm border px-2 py-1 text-[11px] text-foreground @xl:flex">
            <GitMerge className="size-3" aria-hidden /> Merge
          </span>
        </div>
        <div className="grid overflow-hidden rounded-md border bg-card @xl:grid-cols-[206px_1fr]">
          <div className="hidden flex-col border-r @xl:flex">
            <div className="flex items-center gap-1.5 border-b px-2.5 py-2 text-[11px]">
              <span className="flex items-center gap-1 rounded-sm bg-accent px-1.5 py-0.5 font-medium text-foreground">
                <Layers className="size-3" aria-hidden /> Layers
              </span>
              <span className="ml-auto font-mono text-[9.5px] text-faint">4 files</span>
            </div>
            {layers.map(([name, files, on], i) => (
              <Rise key={name} live={live} i={i} className="flex flex-col gap-1 px-2 py-2">
                <span className="flex items-center gap-1.5 text-[11px]">
                  <span className="font-mono text-[9.5px] text-faint">0{i + 1}</span>
                  <span className={cn("truncate", on ? "font-medium text-foreground" : "text-muted-foreground")}>{name}</span>
                </span>
                {files.map(([f, d], j) => (
                  <span
                    key={f}
                    className={cn(
                      "ml-3 flex items-center gap-1.5 rounded-sm border-l-2 px-1.5 py-0.5 font-mono text-[9.5px]",
                      on && j === 0 ? "border-l-primary bg-accent text-foreground" : "border-l-transparent text-muted-foreground",
                    )}
                  >
                    <span className="truncate">{f.split("/").pop()}</span>
                    <span className="ml-auto shrink-0 text-success">{d.split(" ")[0]}</span>
                    {on && j === 0 ? <span className="rounded-[2px] border border-primary/60 px-0.5 text-primary">1</span> : null}
                  </span>
                ))}
              </Rise>
            ))}
            {/* Pinned chat about the change. */}
            <div className="m-2 mt-auto flex flex-col overflow-hidden rounded-md border bg-popover shadow-xl shadow-black/40">
              <p className="flex items-center gap-1.5 border-b px-3 py-2 text-[11px] font-medium text-foreground">
                <MessageSquare className="size-3" aria-hidden /> Chat about this change
              </p>
              <div className="flex flex-col gap-2 p-2.5 text-[11px] leading-[1.5]">
                <Rise live={live} i={0} base={600} className="ml-4 rounded-sm bg-accent px-2 py-1.5 text-foreground">
                  Is this finding a false positive?
                </Rise>
                <div className="flex gap-1.5">
                  <OwlMark className="mt-0.5 size-3.5 shrink-0" />
                  <p className="min-h-[50px] text-muted-foreground">
                    <Streamed
                      live={live}
                      delay={1300}
                      text="No. If commit() fails, the customer already has an email for an invoice that was rolled back."
                    />
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1.5 border-t px-2.5 py-1.5 text-[10.5px] text-faint">
                <Paperclip className="size-3" aria-hidden /> invoices.ts
                <Send className="ml-auto size-3 text-primary" aria-hidden />
              </div>
            </div>
          </div>
          <div className="flex min-w-0 flex-col">
            <div className="flex items-center gap-2 border-b px-3 py-2 font-mono text-[11px]">
              <span className="truncate text-foreground/90">api/invoices.ts</span>
              <span className="ml-auto text-success">+38</span>
              <span className="text-destructive">−4</span>
              <span className="rounded-sm border px-1 text-[9.5px] text-faint">Modified</span>
            </div>
            <div className="py-1.5 font-mono text-[11px] leading-[20px]">
              {DIFF.map((l, i) => (
                <Rise
                  key={l.n}
                  live={live}
                  i={i}
                  step={55}
                  className={cn("flex items-center whitespace-pre", l.hit ? "bg-primary/[0.09]" : "bg-success/[0.05]")}
                >
                  <span className="grid w-4 shrink-0 place-items-center">
                    {l.hit ? <span className="size-1.5 rounded-full bg-primary motion-safe:animate-pulse" /> : null}
                  </span>
                  <span className="w-7 shrink-0 pr-1.5 text-right text-faint">{l.n}</span>
                  <span className={cn("w-3 shrink-0 text-success/80", l.hit && "border-l-2 border-primary pl-0.5")}>+</span>
                  <span className="truncate text-foreground/90">{l.body}</span>
                </Rise>
              ))}
            </div>
            <div className="border-t">
              <p className="flex items-center gap-2 px-3 py-1.5 text-[11px] font-medium text-foreground">
                Findings in this file <span className="rounded-sm border px-1 font-mono text-[9.5px] text-muted-foreground">1</span>
              </p>
              <div className="flex items-center gap-2 border-t px-3 py-2 text-[11px]">
                <span className="rounded-sm border border-caution/50 px-1 text-caution">Minor</span>
                <span className="font-mono text-[10px] text-faint">L27–L28</span>
                <span className="truncate text-foreground/90">Send the email after the commit</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppWindow>
  );
}

/* ── 04 Secure: the Security overview ─────────────────────────────────────── */

function SecurePane({ live }: PaneProps) {
  const tiles: [string, number, string, number?][] = [
    ["Repositories mapped", 3, "Have an attack surface map", 4],
    ["HTTP endpoints", 118, "Across mapped repositories"],
    ["Without auth", 4, "No auth check detected"],
    ["Exposure", 9, "Secrets refs + IaC findings"],
  ];
  const metrics: [string, number, boolean][] = [
    ["HTTP endpoints", 42, false],
    ["Without auth", 3, true],
    ["Outbound calls", 17, false],
    ["Secrets refs", 5, true],
    ["IaC exposure", 1, true],
  ];
  return (
    <AppWindow crumbs={["acme", "Security"]} nav="security">
      <div className="flex flex-col gap-3.5 p-4">
        <div>
          <p className="text-[16px] font-medium tracking-[-0.01em] text-foreground">Security</p>
          <p className="mt-0.5 text-[11.5px] leading-snug text-muted-foreground">
            Attack surface maps for every repository, plus AI security reviews with prioritized risks.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 @xl:grid-cols-4">
          {tiles.map(([label, v, sub, of], i) => (
            <Rise key={label} live={live} i={i} className="rounded-md border bg-card p-1">
              <p className="truncate px-2 pt-1.5 pb-2 text-[11px] font-medium text-foreground">{label}</p>
              <div className="rounded-sm bg-accent/70 px-2 py-2">
                <p className="text-[20px] leading-none font-medium tracking-tight text-foreground">
                  <Counter live={live} to={v} delay={150 + i * 80} />
                  {of ? <span> / {of}</span> : null}
                </p>
                <p className="mt-1.5 truncate text-[10px] text-muted-foreground">{sub}</p>
              </div>
            </Rise>
          ))}
        </div>
        <p className="text-[13px] font-medium text-foreground">Repositories</p>
        <Rise live={live} i={0} base={350} className="overflow-hidden rounded-md border bg-card">
          <div className="flex flex-wrap items-center gap-2 p-3">
            <span className="font-mono text-[11.5px] font-medium text-foreground">acme/payments-api</span>
            <span className="rounded-sm border border-destructive/50 bg-destructive/10 px-1 font-mono text-[10px] text-destructive">Overall: High risk</span>
            <span className="ml-auto hidden items-center gap-1.5 @xl:flex">
              <span className="flex items-center gap-1 rounded-sm border px-2 py-1 text-[10.5px] text-foreground">
                <Radar className="size-3" aria-hidden /> Map attack surface
              </span>
              <span className="flex items-center gap-1 rounded-sm bg-primary px-2 py-1 text-[10.5px] font-medium text-primary-foreground">
                <WandSparkles className="size-3" aria-hidden /> Run security review
              </span>
            </span>
            <p className="w-full text-[11px] text-muted-foreground">Attack surface of main@4e1a9c0, mapped 3h ago</p>
          </div>
          <div className="grid grid-cols-3 gap-1.5 border-t p-3 @xl:grid-cols-5">
            {metrics.map(([k, v, warn], i) => (
              <div key={k} className={cn("rounded-sm border bg-background/60 px-2 py-1.5", i > 2 && "hidden @xl:block")}>
                <p className="truncate font-mono text-[9px] tracking-[0.06em] text-muted-foreground uppercase">{k}</p>
                <p className={cn("mt-1 text-[15px] font-medium", warn ? "text-caution" : "text-foreground")}>
                  <Counter live={live} to={v} delay={500 + i * 70} />
                </p>
              </div>
            ))}
          </div>
        </Rise>
        <Rise live={live} i={1} base={350} className="flex items-center gap-2 rounded-md border bg-card p-3">
          <span className="font-mono text-[11.5px] font-medium text-foreground">acme/web</span>
          <span className="rounded-sm border border-success/40 bg-success/10 px-1 font-mono text-[10px] text-success">Overall: Low risk</span>
        </Rise>
      </div>
    </AppWindow>
  );
}

/* ── Panel ───────────────────────────────────────────────────────────────── */

const TABS = [
  { n: "01", short: "Review", bold: "Review", rest: "every pull request, line by line", Pane: ReviewPane },
  { n: "02", short: "Walkthrough", bold: "Summarize", rest: "what changed and why", Pane: WalkthroughPane },
  { n: "03", short: "Change Stack", bold: "Understand", rest: "big diffs in layers", Pane: ChangeStackPane },
  { n: "04", short: "Secure", bold: "Secure", rest: "code before it merges", Pane: SecurePane },
] as const;

const PROGRESS_CSS = `@keyframes hp-progress{from{transform:scaleX(0)}to{transform:scaleX(1)}}`;

function PaneStage({ children }: { children: ReactNode }) {
  return (
    <div
      className="@container h-full"
      style={{
        backgroundImage: "radial-gradient(color-mix(in oklab, var(--border), transparent 25%) 1px, transparent 1px)",
        backgroundSize: "18px 18px",
      }}
    >
      {children}
    </div>
  );
}

export function LandingProductPanel() {
  const [active, setActive] = useState(0);
  const [cycle, setCycle] = useState(0);
  const [userPaused, setUserPaused] = useState(false);
  const [inView, setInView] = useState(false);
  const [reduced, setReduced] = useState(true);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    const el = root.current;
    if (!el) return () => mq.removeEventListener("change", onChange);
    const io = new IntersectionObserver(([e]) => setInView(Boolean(e?.isIntersecting)), { threshold: 0.25 });
    io.observe(el);
    return () => {
      mq.removeEventListener("change", onChange);
      io.disconnect();
    };
  }, []);

  const auto = !reduced;
  // Keeps advancing under the cursor; pauses only via the pause button or when off-screen.
  const paused = userPaused || !inView;

  const select = (i: number) => {
    setActive(i);
    setCycle((c) => c + 1);
  };
  const next = () => select((active + 1) % TABS.length);

  const progress = (vertical = false) =>
    auto ? (
      <span
        key={`${active}-${cycle}`}
        aria-hidden
        onAnimationEnd={next}
        className={cn("absolute inset-x-0 h-px origin-left bg-primary", vertical ? "bottom-0" : "top-0")}
        style={{
          animation: `hp-progress ${DURATION}ms linear forwards`,
          animationPlayState: paused ? "paused" : "running",
        }}
      />
    ) : null;

  return (
    <div
      ref={root}
      className="relative"
    >
      <style>{PROGRESS_CSS + MOCK_CSS}</style>

      {/* Desktop: four columns; the active one widens, the others show a dimmed peek of their screen. */}
      <div className="hidden h-[620px] overflow-hidden rounded-md border lg:flex">
        {TABS.map((t, i) => {
          const on = active === i;
          return (
            <div
              key={t.n}
              className={cn(
                "relative flex min-w-0 basis-0 flex-col border-r transition-[flex-grow] duration-700 ease-[cubic-bezier(0.22,0.8,0.24,1)] last:border-r-0",
                on ? "grow-[4.6]" : "grow",
              )}
            >
              <button
                type="button"
                aria-pressed={on}
                onClick={() => select(i)}
                className={cn(
                  "relative flex h-14 shrink-0 items-center gap-3 overflow-hidden border-b bg-background px-6 text-left text-[15px] whitespace-nowrap transition-colors",
                  on ? "text-foreground" : "text-faint hover:text-muted-foreground",
                )}
              >
                {on ? progress() : null}
                <span className={cn("font-mono text-[13px]", on ? "text-foreground" : "text-faint")}>{t.n}</span>
                {on ? (
                  <span className="truncate">
                    <span className="font-semibold">{t.bold}</span>{" "}
                    <span className="text-muted-foreground">{t.rest}</span>
                  </span>
                ) : (
                  <span className="truncate font-medium">{t.short}</span>
                )}
              </button>
              <div
                aria-hidden={!on}
                inert={!on}
                className="relative min-h-0 flex-1 overflow-hidden"
              >
                <PaneStage>
                  <div
                    className={cn(
                      "absolute inset-y-0 left-0 w-[max(100%,560px)] px-8 pt-8 xl:w-[max(100%,700px)] transition-[opacity,filter] duration-500",
                      on ? "opacity-100" : "opacity-30 grayscale-[0.4]",
                    )}
                  >
                    <div className="@container">
                      <t.Pane key={on ? `on-${cycle}` : "off"} live={on} />
                    </div>
                  </div>
                </PaneStage>
                {/* Fade the bottom edge, like a screen continuing below the frame. */}
                <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-linear-to-t from-surface to-transparent" />
              </div>
              {!on ? (
                <button
                  type="button"
                  tabIndex={-1}
                  aria-hidden
                  onClick={() => select(i)}
                  className="absolute inset-x-0 top-14 bottom-0 cursor-pointer bg-transparent transition-colors hover:bg-white/[0.02]"
                />
              ) : null}
            </div>
          );
        })}
      </div>

      {/* Mobile / tablet: a tab strip and one pane. */}
      <div className="overflow-hidden rounded-md border lg:hidden">
        <div className="grid grid-cols-4 border-b bg-background">
          {TABS.map((t, i) => {
            const on = active === i;
            return (
              <button
                key={t.n}
                type="button"
                aria-pressed={on}
                onClick={() => select(i)}
                className={cn(
                  "relative flex h-[46px] flex-col items-start justify-center overflow-hidden border-r px-2.5 text-left last:border-r-0 sm:flex-row sm:items-center sm:justify-start sm:gap-2 sm:px-4",
                  on ? "text-foreground" : "text-faint",
                )}
              >
                {on ? progress(true) : null}
                <span className="font-mono text-[10px] sm:text-[12px]">{t.n}</span>
                <span className="w-full truncate text-[12px] font-medium sm:text-[14px]">{t.short}</span>
              </button>
            );
          })}
        </div>
        {/* Fixed height so auto-advancing tabs never make the page jump. */}
        <div className="relative h-[540px] overflow-hidden sm:h-[600px]">
          <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-16 bg-linear-to-t from-surface to-transparent" />
          <PaneStage>
            <div className="p-3 sm:p-6">
              {(() => {
                const P = TABS[active]!.Pane;
                return (
                  <div key={`${active}-${cycle}`} className="@container animate-in fade-in-0 duration-500">
                    <P live />
                  </div>
                );
              })()}
            </div>
          </PaneStage>
        </div>
      </div>

      {auto ? (
        <div className="absolute right-3 bottom-3 z-20 hidden lg:block">
          <button
            type="button"
            onClick={() => setUserPaused((p) => !p)}
            aria-label={userPaused ? "Play product tour" : "Pause product tour"}
            className="grid size-8 place-items-center rounded-sm border bg-background/80 text-muted-foreground backdrop-blur-sm transition-colors hover:text-foreground"
          >
            {userPaused ? <Play className="size-3.5" aria-hidden /> : <Pause className="size-3.5" aria-hidden />}
          </button>
        </div>
      ) : null}
    </div>
  );
}
