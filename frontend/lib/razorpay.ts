import type { Order, VerifyPaymentRequest } from "./api-types";

type RazorpayOptions = {
  key: string; order_id: string; amount: number; currency: string; name: string; description: string;
  prefill: { email?: string; name?: string }; notes: Record<string, string>; theme: { color: string };
  handler: (resp: VerifyPaymentRequest) => void; modal: { ondismiss: () => void };
};
type RazorpayInstance = { open(): void; on(event: "payment.failed", cb: (resp: { error?: { description?: string } }) => void): void };

declare global {
  interface Window { Razorpay?: new (opts: RazorpayOptions) => RazorpayInstance }
}

const SRC = "https://checkout.razorpay.com/v1/checkout.js";
let loading: Promise<void> | null = null;

export function loadCheckout(): Promise<void> {
  if (typeof window !== "undefined" && window.Razorpay) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SRC;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => { loading = null; reject(new Error("Could not load Razorpay Checkout")); };
    document.body.appendChild(s);
  });
  return loading;
}

export async function openCheckout(order: Order, h: {
  onSuccess: (r: VerifyPaymentRequest) => void; onDismiss: () => void; onFailure: (message: string) => void;
}): Promise<void> {
  await loadCheckout();
  const Rzp = window.Razorpay;
  if (!Rzp) throw new Error("Razorpay Checkout unavailable");
  const rzp = new Rzp({
    key: order.key_id, order_id: order.order_id, amount: order.amount_paise, currency: order.currency,
    name: order.name, description: order.description,
    prefill: { email: order.prefill.email ?? undefined, name: order.prefill.name ?? undefined },
    notes: { mode: "TEST" }, theme: { color: "#f5b942" },
    handler: h.onSuccess, modal: { ondismiss: h.onDismiss },
  });
  rzp.on("payment.failed", (r) => h.onFailure(r.error?.description ?? "Payment failed"));
  rzp.open();
}
