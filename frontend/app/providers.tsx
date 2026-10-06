"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";
import { ShellSlotsProvider } from "@/components/cr/shell-slots";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            // 4xx answers (401, 404, 422, ...) will not change on retry: show them right away.
            retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 3,
          },
        },
      }),
  );
  // Dark only, like CodeRabbit: no light theme or theme switcher.
  return (
    <ThemeProvider attribute="class" forcedTheme="dark" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <ShellSlotsProvider>{children}</ShellSlotsProvider>
          <Toaster position="top-right" offset={64} />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
