import type { Provider } from "@/lib/api-types";
import { cn } from "@/lib/utils";

/** GitHub / GitLab mark in currentColor (size-4 by default). */
export function ProviderIcon({ provider, className }: { provider: Provider | string; className?: string }) {
  if (provider === "gitlab")
    return (
      <svg viewBox="0 0 24 24" className={cn("size-4", className)} aria-hidden fill="currentColor">
      <path d="m23.6 9.6-.03-.09L20.3.97a.85.85 0 0 0-1.62.06l-2.2 6.75H7.53L5.33 1.03A.85.85 0 0 0 3.7.97L.44 9.5l-.03.09a6.06 6.06 0 0 0 2.01 7l.01.01.03.02 4.98 3.73 2.46 1.86 1.5 1.13a1 1 0 0 0 1.22 0l1.5-1.13 2.46-1.86 5.01-3.75.01-.01a6.06 6.06 0 0 0 2-7Z" />
      </svg>
    );
  return (
    <svg viewBox="0 0 16 16" className={cn("size-4", className)} aria-hidden fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
