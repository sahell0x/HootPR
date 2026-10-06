"use client";
import { RotateCw } from "lucide-react";
import { useEffect } from "react";
import { ShellErrorFrame, ShellErrorLink, ShellErrorPanel } from "@/components/cr/shell-error";
import { Button } from "@/components/ui/button";

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <ShellErrorFrame>
      <ShellErrorPanel
        role="alert"
        code="500"
        title="Something went wrong."
        description={
          <>
            This page hit an unexpected error. Try again, or head back to your organizations.
            {error.digest ? <span className="mt-2 block font-mono text-xs text-faint">ref {error.digest}</span> : null}
          </>
        }
        actions={
          <>
            <Button variant="inverse" onClick={() => reset()}>
              <RotateCw aria-hidden /> Try again
            </Button>
            <ShellErrorLink href="/orgs">Go to organizations</ShellErrorLink>
          </>
        }
      />
    </ShellErrorFrame>
  );
}
