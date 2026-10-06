import { Info } from "lucide-react";
import type { CreditReceipt, ReceiptLine } from "@/lib/api-types";
import { formatCredits } from "@/lib/format";
import { cn } from "@/lib/utils";

const SEGMENT = ["var(--chart-1)", "var(--chart-3)", "var(--chart-2)", "var(--chart-4)", "var(--chart-5)"];
const cr = formatCredits;
const int = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-US"));
/** Owner-only token / $ fields: present only for platform owners, never rendered otherwise. */
const hasInternals = (l: ReceiptLine) =>
  l.input_tokens != null || l.cached_tokens != null || l.output_tokens != null || l.cost_usd != null;

/**
 * Credit receipt of a metered job (reserve → meter → settle): one row per metered stage, a stacked share bar,
 * the final charge and what was returned from the reservation. Platform owners also get tokens, $ cost
 * and the credit/cost margin, labelled "Owner only".
 */
export function CreditReceiptCard({ receipt, subject = "review" }: { receipt: CreditReceipt; subject?: string }) {
  const lines = receipt.lines;
  const owner = lines.some(hasInternals);
  const metered = lines.reduce((a, l) => a + Number(l.credits), 0);
  const costUsd = lines.reduce((a, l) => a + Number(l.cost_usd ?? 0), 0);
  const charged = Number(receipt.charged);
  const color = (i: number) => SEGMENT[i % SEGMENT.length];
  const cell = "px-4 py-2 sm:px-5";
  const num = "text-right font-mono text-xs tabular-nums";
  return (
    <div className="flex flex-col divide-y" data-testid="credit-receipt">
      {metered > 0 ? (
        <div className="flex flex-col gap-2 p-4 sm:p-5">
          <div className="flex h-2 w-full overflow-hidden rounded-sm bg-subtle" role="img" aria-label="Credits by stage">
            {lines.map((l, i) =>
              Number(l.credits) > 0 ? (
                <span
                  key={l.stage}
                  title={`${l.label}: ${cr(l.credits)}`}
                  className="h-full"
                  style={{ width: `${(Number(l.credits) / metered) * 100}%`, background: color(i) }}
                />
              ) : null,
            )}
          </div>
        </div>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className={cn(cell, "text-left font-normal")}>Stage</th>
              {owner ? (
                <>
                  <th scope="col" className={cn(cell, "text-right font-normal")}>In</th>
                  <th scope="col" className={cn(cell, "text-right font-normal")}>Cached</th>
                  <th scope="col" className={cn(cell, "text-right font-normal")}>Out</th>
                  <th scope="col" className={cn(cell, "text-right font-normal")}>Cost</th>
                </>
              ) : null}
              <th scope="col" className={cn(cell, "text-right font-normal")}>Credits</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={l.stage} className="border-t">
                <td className={cell}>
                  <span className="inline-flex items-center gap-2">
                    <span className="size-2 shrink-0 rounded-[2px]" style={{ background: color(i) }} aria-hidden />
                    {l.label}
                  </span>
                </td>
                {owner ? (
                  <>
                    <td className={cn(cell, num, "text-muted-foreground")}>{int(l.input_tokens)}</td>
                    <td className={cn(cell, num, "text-muted-foreground")}>{int(l.cached_tokens)}</td>
                    <td className={cn(cell, num, "text-muted-foreground")}>{int(l.output_tokens)}</td>
                    <td className={cn(cell, num, "text-muted-foreground")}>{l.cost_usd == null ? "—" : `$${l.cost_usd}`}</td>
                  </>
                ) : null}
                <td className={cn(cell, num)}>{cr(l.credits)}</td>
              </tr>
            ))}
            <tr className="border-t font-medium">
              <th scope="row" className={cn(cell, "text-left font-medium")}>Charged</th>
              {owner ? <td colSpan={4} /> : null}
              <td className={cn(cell, num, "text-sm")} data-testid="receipt-charged">{cr(receipt.charged)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="flex flex-col gap-1.5 p-4 text-sm text-muted-foreground sm:px-5">
        <p className="tabular-nums">
          Reserved {cr(receipt.reserved)} · Returned {cr(receipt.refunded)}
        </p>
        {receipt.legacy ? (
          <p className="flex items-center gap-1.5 text-xs" data-testid="receipt-legacy">
            <Info className="size-3.5 shrink-0" aria-hidden /> This {subject} was billed at the flat rate used before usage metering.
          </p>
        ) : null}
        {receipt.minimum_applied ? (
          <p className="flex items-center gap-1.5"><Info className="size-3.5 shrink-0" aria-hidden /> Minimum charge applied</p>
        ) : null}
        {receipt.budget_reached ? (
          <p className="flex items-center gap-1.5 text-caution"><Info className="size-3.5 shrink-0" aria-hidden /> Review trimmed to fit the reserved credits</p>
        ) : null}
      </div>
      {owner ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 p-4 text-sm sm:px-5" data-testid="receipt-margin">
          <span className="eyebrow rounded-sm border border-caution/40 px-1.5 text-caution">Owner only</span>
          <span className="text-muted-foreground">
            Margin: <span className="font-mono text-xs text-foreground tabular-nums">{cr(charged)}</span> credits charged vs{" "}
            <span className="font-mono text-xs text-foreground tabular-nums">${costUsd.toFixed(4)}</span> provider cost
            {charged > 0 ? (
              <> · <span className="font-mono text-xs text-foreground tabular-nums">${((costUsd / charged) * 100).toFixed(4)}</span> per 100 credits</>
            ) : null}
          </span>
        </div>
      ) : null}
    </div>
  );
}
