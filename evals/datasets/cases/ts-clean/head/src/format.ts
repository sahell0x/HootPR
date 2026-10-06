const CENTS_PER_DOLLAR = 100;

/** Format an amount in cents as US dollars, e.g. 1999 -> "$19.99". */
export function formatPrice(cents: number): string {
  return "$" + (cents / CENTS_PER_DOLLAR).toFixed(2);
}
