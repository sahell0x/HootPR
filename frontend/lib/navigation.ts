/** Only same-origin absolute paths are allowed as post-login destinations (no open redirects). */
export function safeNext(next: string | null | undefined): string | undefined {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return undefined;
  return next;
}
