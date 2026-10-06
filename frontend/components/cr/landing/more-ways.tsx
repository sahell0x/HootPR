import type { ReactNode } from "react";
import {
  AnalyticsMock,
  ChatMock,
  ChecksMock,
  FinishingMock,
  LedgerMock,
  ReportMock,
} from "@/components/cr/landing/c-mocks";
import { CReveal } from "@/components/cr/landing/c-reveal";
import { CONTAINER, Eyebrow } from "@/components/cr/landing/shared";
import { cn } from "@/lib/utils";

const STEPS = [
  { title: "Sign in", body: "With GitHub or GitLab." },
  { title: "Install on your repos", body: "Pick the repositories or projects HootPR may read." },
  { title: "Open a pull request", body: "Reviews start on open and on every new commit." },
  { title: "Read the walkthrough", body: "A summary comment, inline findings and a HootPR check." },
];

function Card({
  title,
  body,
  visual,
  className,
  delay,
}: {
  title: string;
  body: string;
  visual: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <CReveal delay={delay} className={cn("h-full min-w-0", className)}>
      <article className="group flex h-full flex-col overflow-hidden rounded-md border bg-card/60 transition-[transform,border-color,box-shadow] duration-300 ease-out hover:-translate-y-1 hover:border-white/15 hover:shadow-[0_18px_50px_-20px_rgba(255,87,10,0.25)] motion-reduce:hover:translate-y-0">
        <div
          aria-hidden
          className="relative flex flex-1 flex-col justify-start overflow-hidden bg-[radial-gradient(120%_90%_at_50%_0%,rgba(255,87,10,0.06),transparent_60%)] px-5 pt-5 pb-2 sm:px-6 sm:pt-6"
        >
          {visual}
        </div>
        <div className="px-5 pt-4 pb-6 sm:px-6">
          <h3 className="text-[20px] leading-7 font-medium tracking-[-0.02em] text-foreground">{title}</h3>
          <p className="mt-2 text-[15px] leading-6 text-muted-foreground">{body}</p>
        </div>
      </article>
    </CReveal>
  );
}

export function MoreWaysSection() {
  return (
    <section id="more" aria-labelledby="more-title" className="scroll-mt-20">
      <div className={cn(CONTAINER, "py-20 md:py-24")}>
        <CReveal>
          <Eyebrow>Beyond the review</Eyebrow>
          <h2 id="more-title" className="mt-4 text-[32px] leading-[1.1] font-medium tracking-[-0.03em] sm:text-[40px]">
            More ways to ship with confidence.
          </h2>
          <p className="mt-5 max-w-[60ch] text-lg leading-7 text-muted-foreground">
            The same context that powers each review answers questions, writes the boring parts and keeps the whole
            team in the loop.
          </p>
        </CReveal>

        <div className="mt-14 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Card
            className="md:col-span-2 lg:row-span-2"
            title="Chat with @hootpr in the PR"
            body="Mention @hootpr on any finding to ask why, push back or get a fix. It answers in the same thread, and what you teach it becomes a learning for that repository."
            visual={<ChatMock />}
          />
          <Card
            delay={120}
            title="Pre-merge checks"
            body="Title, description, docstring coverage and linked issues, plus your own checks in plain English. Run them as warnings or as errors that fail the HootPR status."
            visual={<ChecksMock />}
          />
          <Card
            delay={240}
            title="Finishing touches"
            body="Comment “generate docstrings” or “generate unit tests”. HootPR writes them in a sandbox, runs your tests and opens a stacked PR."
            visual={<FinishingMock />}
          />
          <Card
            delay={0}
            title="Reports by email"
            body="Ask for any summary of your review data, or schedule a daily, weekly or monthly digest by email."
            visual={<ReportMock />}
          />
          <Card
            delay={120}
            title="Dashboard analytics"
            body="Reviews, findings, acceptance rate and time to first review, broken down by repository and author."
            visual={<AnalyticsMock />}
          />
          <Card
            delay={240}
            title="Credits you can audit"
            body="Every hold, charge, refund and credit pack is a line in your organization’s ledger. New organizations start with free credits."
            visual={<LedgerMock />}
          />
        </div>

        <div id="how" className="mt-24 scroll-mt-20">
          <CReveal>
            <Eyebrow>How it works</Eyebrow>
            <h3 className="mt-4 text-[26px] leading-tight font-medium tracking-[-0.02em] sm:text-[32px]">
              From sign-in to first review in minutes.
            </h3>
          </CReveal>
          <CReveal delay={100} className="mt-10">
            <ol className="relative grid overflow-hidden rounded-md border sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((s, i) => (
                <li
                  key={s.title}
                  className={cn(
                    "relative flex flex-col gap-2 p-6 lg:p-7",
                    i > 0 && "border-t sm:border-t-0",
                    i % 2 === 1 && "sm:border-l",
                    i >= 2 && "sm:border-t lg:border-t-0",
                    i === 2 && "lg:border-l",
                  )}
                >
                  <div className="flex items-center gap-3">
                    <span className="grid size-7 place-items-center rounded-full border border-primary/40 bg-primary/10 font-mono text-[12px] text-primary">
                      {i + 1}
                    </span>
                    {i < STEPS.length - 1 ? (
                      <span aria-hidden className="hidden h-px flex-1 bg-gradient-to-r from-primary/40 to-transparent lg:block" />
                    ) : null}
                  </div>
                  <p className="mt-4 text-[17px] font-medium text-foreground">{s.title}</p>
                  <p className="text-[15px] leading-6 text-muted-foreground">{s.body}</p>
                </li>
              ))}
            </ol>
          </CReveal>
        </div>
      </div>
    </section>
  );
}
