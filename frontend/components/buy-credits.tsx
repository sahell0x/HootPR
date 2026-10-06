"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, ApiError } from "@/lib/api";
import type { Billing } from "@/lib/api-types";
import { DISCLAIMER } from "@/lib/disclaimer";
import { formatCredits, formatInr } from "@/lib/format";
import { qk } from "@/lib/queries";
import { openCheckout } from "@/lib/razorpay";

export function BuyCredits({ slug, billing, canBuy }: { slug: string; billing: Billing; canBuy: boolean }) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const buy = useMutation({
    mutationFn: async () => {
      const order = await api.createOrder(slug);
      await openCheckout(order, {
        onSuccess: async (resp) => {
          try {
            const res = await api.verifyPayment(resp);
            toast.success(`Added ${formatCredits(res.credits_added)} credits`);
            await qc.invalidateQueries({ queryKey: qk.billing(slug) });
            await qc.invalidateQueries({ queryKey: qk.org(slug) });
          } catch (e) {
            toast.error(e instanceof ApiError ? e.message : "Payment verification failed");
          }
        },
        onDismiss: async () => {
          toast.message("Checkout closed — no payment was made.");
          // Free the purchase slot the open order was holding.
          await api.cancelOrder(slug, order.order_id).catch(() => undefined);
          await qc.invalidateQueries({ queryKey: qk.billing(slug) });
        },
        onFailure: (m) => toast.error(m),
      });
    },
    onError: (e) => toast.error(e instanceof ApiError && e.code === "billing_not_configured"
      ? "Billing is not configured on this server." : e instanceof Error ? e.message : "Could not start checkout"),
  });
  const price = formatInr(billing.pack.price_paise);
  const start = () => {
    // Test-mode payments are explained at the moment of buying, not across the site.
    if (billing.test_mode) setConfirming(true);
    else buy.mutate();
  };
  return (
    <div className="flex flex-col gap-2">
      <Button size="lg" className="h-10 w-full" disabled={!canBuy || !billing.can_purchase || buy.isPending} onClick={start}>
        {buy.isPending ? <Loader2 aria-hidden className="animate-spin" /> : null}
        {`Buy ${formatCredits(billing.pack.credits)} credits for ${price}`}
      </Button>
      {!billing.can_purchase && billing.purchase_blocked_reason ? (
        <p className="text-xs text-caution">{billing.purchase_blocked_reason}</p>
      ) : null}
      {!canBuy ? <p className="text-xs text-muted-foreground">Only admins and billing admins can buy credits.</p> : null}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FlaskConical aria-hidden className="size-4 text-caution" /> Test mode — no real money
            </DialogTitle>
            <DialogDescription>{DISCLAIMER}</DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-md border bg-subtle px-4 py-3 text-sm">
            <dt className="text-muted-foreground">Card</dt>
            <dd className="font-mono">4100 2800 0000 1007 <span className="font-sans text-muted-foreground">· any future expiry, any CVV</span></dd>
            <dt className="text-muted-foreground">UPI</dt>
            <dd className="font-mono">success@razorpay</dd>
          </dl>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>Cancel</Button>
            <Button onClick={() => { setConfirming(false); buy.mutate(); }}>
              Continue to checkout · {price}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
