"use client";
import { Check, ChevronRight, ReceiptText } from "lucide-react";
import Link from "next/link";
import { Fragment, type ReactNode, useState } from "react";
import { useParams } from "next/navigation";
import { EmptyState } from "@/components/cr/dash-ui";
import { SectionTitle, StatusPill, TablePagination } from "@/components/cr/kit";
import { PageContainer, PageHeader } from "@/components/cr/page-header";
import { fmtDateTime, usePaged } from "@/components/cr/pages-table";
import { StatGrid, StatTile } from "@/components/cr/stat-tile";
import { BuyCredits } from "@/components/buy-credits";
import { CreditReceiptCard } from "@/components/credit-receipt";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { LedgerEntry, Metering, OwnerUsage } from "@/lib/api-types";
import { TYPICAL_REVIEW_CREDITS, creditsLabel, formatCredits, formatInr, reviewsFor } from "@/lib/format";
import { useBilling, useMeta, useOrg, useReceipt } from "@/lib/queries";
import { cn } from "@/lib/utils";

const REASON: Record<string, string> = { signup_bonus: "Signup bonus", purchase: "Credit pack (test)",
  review_hold: "Reserved for review", review: "Review settled", chat: "Chat reply", finishing: "Finishing touch",
  security: "Security review", security_review: "Security review", refund: "Refund", manual: "Manual adjustment" };

type Tone = "neutral" | "primary" | "success" | "warning" | "danger";
const REASON_TONE: Record<string, Tone> = { signup_bonus: "success", purchase: "primary", refund: "success",
  review_hold: "warning", review: "neutral", chat: "neutral", finishing: "neutral", security: "neutral",
  security_review: "neutral", manual: "neutral" };

/** What a hold/settle row's job is, from its ref (holds always use the `review_hold` reason). */
const JOB: Record<string, string> = { review: "review", chat: "chat reply", change_stack_chat: "chat reply",
  finishing: "finishing touch", security_scan: "security review" };
const SETTLE_REASONS = new Set(["review", "chat", "finishing", "security", "security_review"]);

function reasonLabel(e: LedgerEntry): string {
  const job = e.ref_type ? JOB[e.ref_type] : undefined;
  if (job && e.reason === "review_hold") return `Reserved for ${job}`;
  if (job && SETTLE_REASONS.has(e.reason)) return `${job.charAt(0).toUpperCase()}${job.slice(1)} settled`;
  return REASON[e.reason] ?? e.reason;
}

/** Reason badge, settle summary and what the movement was for (linked when the API gives an `href`). */
function LedgerType({ e }: { e: LedgerEntry }) {
  const reason = reasonLabel(e);
  return (
    <div className="flex flex-col gap-1">
      <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusPill tone={REASON_TONE[e.reason] ?? "neutral"}>{reason}</StatusPill>
        {e.charged != null ? (
          <span className="text-xs text-muted-foreground tabular-nums">
            charged {formatCredits(e.charged)} — returned {formatCredits(e.delta)}
          </span>
        ) : null}
      </span>
      {e.description ? (
        e.href ? (
          <Link href={e.href} className="max-w-md truncate text-xs text-muted-foreground hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            aria-label={`${reason} — ${e.description}`} data-testid="ledger-description">
            {e.description}
          </Link>
        ) : (
          <span className="max-w-md truncate text-xs text-muted-foreground" data-testid="ledger-description">{e.description}</span>
        )
      ) : null}
    </div>
  );
}

const RECEIPT_SUBJECT: Record<string, string> = { review: "review", chat: "chat reply", change_stack_chat: "chat reply",
  finishing: "finishing touch", security_scan: "security review" };

/** Lazily loaded credit receipt under an expanded ledger row. */
function LedgerReceipt({ slug, e }: { slug: string; e: LedgerEntry }) {
  const q = useReceipt(slug, e.ref_type ?? "", e.ref_id ?? "");
  if (q.isPending) return <Skeleton className="m-4 h-24" />;
  if (q.error || !q.data)
    return <p className="p-4 text-sm text-muted-foreground">The receipt for this charge is not available.</p>;
  return <CreditReceiptCard receipt={q.data} subject={RECEIPT_SUBJECT[e.ref_type ?? ""] ?? "charge"} />;
}

function LedgerRow({ slug, e }: { slug: string; e: LedgerEntry }) {
  const [open, setOpen] = useState(false);
  const expandable = Boolean(e.ref_type && e.ref_id && (e.has_receipt ?? e.charged != null));
  const panelId = `receipt-${e.id}`;
  return (
    <Fragment>
      <TableRow>
        <TableCell className="w-8 pr-0">
          {expandable ? (
            <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls={panelId}
              aria-label={open ? "Hide credit receipt" : "Show credit receipt"}
              className="inline-flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:bg-subtle hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              <ChevronRight aria-hidden className={cn("size-4 transition-transform", open && "rotate-90")} />
            </button>
          ) : null}
        </TableCell>
        <TableCell className="whitespace-nowrap text-muted-foreground">{fmtDateTime(e.created_at)}</TableCell>
        <TableCell><LedgerType e={e} /></TableCell>
        <TableCell className={`text-right font-mono text-xs tabular-nums ${Number(e.delta) < 0 ? "text-destructive" : "text-success"}`}>
          {Number(e.delta) > 0 ? "+" : ""}{formatCredits(e.delta)}
        </TableCell>
        <TableCell className="text-right font-mono text-xs tabular-nums">{formatCredits(e.balance_after)}</TableCell>
      </TableRow>
      {expandable && open ? (
        <TableRow id={panelId} className="hover:bg-transparent">
          <TableCell colSpan={5} className="p-0">
            <div className="m-3 overflow-hidden rounded-md border bg-card"><LedgerReceipt slug={slug} e={e} /></div>
          </TableCell>
        </TableRow>
      ) : null}
    </Fragment>
  );
}

const usd = (v: number) => `$${v.toFixed(4)}`;

/** Platform owners only: metered credits billed to jobs vs unbilled background work, and provider cost. */
function OwnerUsageCard({ usage }: { usage: OwnerUsage }) {
  const cost = Number(usage.cost_usd);
  const charged = Number(usage.charged_credits);
  const num = "font-mono text-xs text-foreground tabular-nums";
  return (
    <section aria-labelledby="owner-usage-h" data-testid="owner-usage">
      <SectionTitle>
        <span className="inline-flex items-center gap-2">
          <span id="owner-usage-h">Usage, last 30 days</span>
          <span className="eyebrow rounded-sm border border-caution/40 px-1.5 text-caution">Owner only</span>
        </span>
      </SectionTitle>
      <div className="overflow-hidden rounded-md border bg-card">
        <dl className="grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Billed credits", formatCredits(usage.billed_credits), "Metered on paying jobs"],
            ["Unbilled credits", formatCredits(usage.unbilled_credits), "Background work nobody is charged for"],
            ["Charged", formatCredits(usage.charged_credits), "Credits settled on this org"],
            ["Provider cost", usd(cost), charged > 0 ? `${usd((cost / charged) * 100)} per 100 credits charged` : "No charges yet"],
          ].map(([label, value, hint]) => (
            <div key={label} className="flex flex-col gap-1 bg-card p-4 sm:p-5">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="text-xl font-medium tracking-tight tabular-nums">{value}</dd>
              <dd className="text-xs text-faint">{hint}</dd>
            </div>
          ))}
        </dl>
        {usage.by_source.length ? (
          <ul className="flex flex-col divide-y border-t text-sm" aria-label="Unbilled work by source">
            {usage.by_source.map((s) => (
              <li key={s.source} className="flex items-center justify-between gap-3 px-4 py-2 sm:px-5">
                <span className="text-muted-foreground">{s.source.replace(/_/g, " ")}</span>
                <span className="flex gap-4">
                  <span className={num}>{formatCredits(s.credits)} credits</span>
                  <span className={cn(num, "text-muted-foreground")}>{s.cost_usd == null ? "—" : usd(Number(s.cost_usd))}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}

const STEPS = (m: Metering | null | undefined): { title: string; body: ReactNode }[] => [
  { title: "Reserve", body: <>Each review reserves credits up front based on the pull request&apos;s size{m ? <>, up to {creditsLabel(m.review_hold_max)}</> : null}.</> },
  { title: "Meter", body: "The AI work actually done is metered stage by stage — triage, review agents, verification, walkthrough." },
  { title: "Charge", body: <>You pay for what was used{m ? <>, with a minimum of {creditsLabel(m.review_min_charge)} per review</> : null}.</> },
  { title: "Return", body: "Whatever was reserved but not used goes back to your balance instantly." },
];

/** "How credits are metered": reserve → meter → charge → return, plus the org's recent average. */
function MeteringSection({ metering }: { metering: Metering | null | undefined }) {
  const avg = metering?.avg_review_credits_30d;
  return (
    <section aria-labelledby="metering-h">
      <SectionTitle><span id="metering-h">How credits are metered</span></SectionTitle>
      <div className="overflow-hidden rounded-md border bg-card">
        <ol className="grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-4">
          {STEPS(metering).map((st, i) => (
            <li key={st.title} className="flex flex-col gap-1.5 bg-card p-4 sm:p-5">
              <span className="font-mono text-xs text-faint">{String(i + 1).padStart(2, "0")}</span>
              <p className="text-sm font-medium">{st.title}</p>
              <p className="text-sm leading-relaxed text-muted-foreground">{st.body}</p>
            </li>
          ))}
        </ol>
        <p className="border-t px-4 py-3 text-sm text-muted-foreground sm:px-5" data-testid="metering-average">
          {metering && avg != null && metering.reviews_30d > 0 ? (
            <>Average review: <span className="font-medium text-foreground tabular-nums">{creditsLabel(avg)}</span>{" "}
              (last 30 days, {metering.reviews_30d} {metering.reviews_30d === 1 ? "review" : "reviews"})</>
          ) : (
            <>Billed by actual AI usage — a typical review is about {creditsLabel(TYPICAL_REVIEW_CREDITS)}.</>
          )}
        </p>
      </div>
    </section>
  );
}

function Feature({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-start gap-2.5">
      <Check aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success" />
      <span>{children}</span>
    </li>
  );
}

/** Pricing-page style plan column: name, blurb, big price + muted period, CTA, check-list. */
function PlanCard({ name, tag, blurb, price, period, note, cta, features, highlight }: {
  name: string; tag?: ReactNode; blurb: ReactNode; price: ReactNode; period: ReactNode; note: ReactNode;
  cta: ReactNode; features: ReactNode; highlight?: boolean;
}) {
  return (
    <div className="relative flex flex-col bg-card p-6">
      {highlight ? <span aria-hidden className="absolute inset-x-0 top-0 h-0.5 bg-primary" /> : null}
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-medium tracking-tight">{name}</h3>
        {tag}
      </div>
      <p className="mt-2 min-h-10 text-sm text-muted-foreground">{blurb}</p>
      <p className="mt-6 flex flex-wrap items-baseline gap-x-1.5">
        <span className="text-4xl font-medium tracking-tight tabular-nums">{price}</span>
        <span className="text-sm text-muted-foreground">{period}</span>
      </p>
      <p className="mt-1 text-sm text-faint">{note}</p>
      <div className="mt-6">{cta}</div>
      <ul className="mt-6 flex flex-col gap-2.5 border-t pt-6 text-sm text-muted-foreground">{features}</ul>
    </div>
  );
}

export default function BillingPage() {
  const { org: slug } = useParams<{ org: string }>();
  const org = useOrg(slug);
  const billing = useBilling(slug);
  const meta = useMeta();
  const data = billing.data;
  const pg = usePaged(data?.ledger ?? []);
  if (!data || !org.data) {
    const error = org.error ?? billing.error;
    if (error) return <QueryState error={error} what="This organization" backHref="/orgs" />;
    return (
      <PageContainer className="flex flex-col gap-6">
        <div className="flex flex-col gap-2"><Skeleton className="h-7 w-32" /><Skeleton className="h-4 w-96 max-w-full" /></div>
        <Skeleton className="h-16" />
        <div className="grid gap-3 sm:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}</div>
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-[450px]" />
      </PageContainer>
    );
  }
  const prices = meta.data?.credit_prices;
  const canBuy = org.data.role === "admin" || org.data.role === "billing_admin";
  const packsLeft = Math.max(0, data.max_purchases - data.purchases_count);
  const ledger = data.ledger;
  const balance = Number(data.balance);
  const metering = data.metering;
  const low = metering ? balance < Number(metering.review_min_charge) : balance <= 0;
  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        className="mb-0"
        title="Billing"
        description="Credits pay for reviews and chat replies, billed by actual AI usage. Top up with a credit pack when you run low."
      />

      <StatGrid className="mb-0 grid-cols-1 sm:grid-cols-3 lg:grid-cols-3">
        <StatTile
          label="Balance"
          className={low ? "border-caution/40" : undefined}
          value={<><span className={low ? "text-caution" : undefined}>{formatCredits(data.balance)}</span> <span className="text-sm font-normal text-muted-foreground">credits</span></>}
          hint={<>
            <span className="block">Billed by actual AI usage — a typical review is about {creditsLabel(TYPICAL_REVIEW_CREDITS)}</span>
            {low ? <span className="mt-0.5 block text-caution">Not enough for a review — buy a credit pack below.</span> : null}
          </>}
        />
        <StatTile label="Packs" value={`${data.purchases_count} / ${data.max_purchases} ${data.max_purchases === 1 ? "pack" : "packs"} bought`}
          hint={packsLeft ? `${packsLeft} more available` : "Pack limit reached"} />
        <StatTile label="Maximum balance" value={<>{formatCredits(data.max_balance)} <span className="text-sm font-normal text-muted-foreground">credits</span></>}
          hint="Balance cap per organization" />
      </StatGrid>

      <section>
        <SectionTitle>Plans &amp; credits</SectionTitle>
        <div className={`grid gap-px overflow-hidden rounded-md border bg-border ${prices ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
          {prices ? (
            <PlanCard
              name="Starter"
              blurb="Every new organization starts with free credits to try HootPR."
              price={formatInr(0)}
              period={`/ ${creditsLabel(prices.signup_bonus)}`}
              note="Added once at signup"
              cta={<div className="flex h-10 w-full items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">Included automatically</div>}
              features={<>
                <Feature>≈ {reviewsFor(prices.signup_bonus, TYPICAL_REVIEW_CREDITS)} typical pull request reviews</Feature>
                <Feature>Reviews, chat and learnings</Feature>
                <Feature>No card required</Feature>
              </>}
            />
          ) : null}
          <PlanCard
            highlight
            name="Credit pack"
            tag={<span className="eyebrow rounded-sm border border-primary/40 px-1.5 text-primary">One-time</span>}
            blurb={<>{formatCredits(data.pack.credits)} review credits added to your organization&apos;s balance instantly.</>}
            price={formatInr(data.pack.price_paise)}
            period={`/ ${formatCredits(data.pack.credits)} credits`}
            note="Paid once"
            cta={<BuyCredits slug={slug} billing={data} canBuy={canBuy} />}
            features={<>
              <Feature>{formatCredits(data.pack.credits)} credits per pack</Feature>
              <Feature>≈ {reviewsFor(data.pack.credits, TYPICAL_REVIEW_CREDITS)} typical pull request reviews</Feature>
              <Feature>Up to {data.max_purchases} {data.max_purchases === 1 ? "pack" : "packs"} per organization</Feature>
              <Feature>Pay by card or UPI via Razorpay</Feature>
            </>}
          />
          <PlanCard
            name="How credits are spent"
            blurb="Billed by actual AI usage. Unused reserved credits are returned the moment a job finishes."
            price={`≈ ${formatCredits(TYPICAL_REVIEW_CREDITS)}`}
            period="credit / typical review"
            note={`Balance capped at ${formatCredits(data.max_balance)} credits`}
            cta={<div className="flex h-10 w-full items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">Pay as you go</div>}
            features={<>
              {metering ? <Feature>Reviews from {creditsLabel(metering.review_min_charge)}, never more than {creditsLabel(metering.review_hold_max)}</Feature> : null}
              {metering ? <Feature>Chat replies from {creditsLabel(metering.chat_min_charge)}</Feature> : null}
              {prices ? <Feature>Signup bonus — {creditsLabel(prices.signup_bonus)}</Feature> : null}
              <Feature>Failed reviews are refunded automatically</Feature>
              <Feature>Every movement is recorded in the ledger below</Feature>
            </>}
          />
        </div>
      </section>

      <MeteringSection metering={metering} />

      {data.usage_30d ? <OwnerUsageCard usage={data.usage_30d} /> : null}

      <section>
        <SectionTitle>Credit ledger</SectionTitle>
        {ledger.length === 0 ? (
          <EmptyState icon={ReceiptText} title="No credit movements yet">Purchases, review charges and refunds appear here.</EmptyState>
        ) : (
          <div>
            <Table>
              <TableHeader><TableRow><TableHead className="w-8 pr-0"><span className="sr-only">Receipt</span></TableHead><TableHead>Date</TableHead><TableHead>Type</TableHead><TableHead className="text-right">Change</TableHead><TableHead className="text-right">Balance</TableHead></TableRow></TableHeader>
              <TableBody>
                {pg.pageRows.map((e) => <LedgerRow key={e.id} slug={slug} e={e} />)}
              </TableBody>
            </Table>
            <TablePagination {...pg} />
          </div>
        )}
      </section>
    </PageContainer>
  );
}
