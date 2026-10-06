import { CircleAlert } from "lucide-react";
import Link from "next/link";
import { Brand } from "@/components/brand";
import { ProviderButtons } from "@/components/provider-buttons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { safeNext } from "@/lib/navigation";

const ERRORS: Record<string, string> = {
  oauth_state_invalid: "Your sign-in link expired. Please try again.",
  oauth_failed: "GitHub/GitLab did not complete the sign-in. Please try again.",
  identity_in_use: "That account is already linked to another HootPR user.",
  provider_not_configured:
    "Sign-in with that provider is not configured on this server. Ask the operator to add its OAuth keys.",
};

/** Faint dot grid + fine grain for the left panel (CSS only, no images). */
const TEXTURE: React.CSSProperties = {
  backgroundImage:
    "radial-gradient(color-mix(in oklab, var(--foreground), transparent 90%) 1px, transparent 1px), radial-gradient(color-mix(in oklab, var(--foreground), transparent 95%) 1px, transparent 1px)",
  backgroundSize: "22px 22px, 5px 5px",
  backgroundPosition: "0 0, 2px 3px",
};

export function LoginView({ error, next }: { error?: string | null; next?: string | null }) {
  return (
    <main className="grid min-h-[calc(100svh-var(--banner-h,0px))] flex-1 bg-background lg:grid-cols-[1fr_440px]">
      <section
        aria-label="About HootPR"
        className="relative hidden flex-col items-center justify-center border-r px-10 lg:flex"
        style={TEXTURE}
      >
        <Brand className="absolute top-8 left-10 text-base font-medium" />
        <div className="flex max-w-[520px] flex-col items-center gap-5 text-center">
          <p className="text-[40px] leading-[1.15] font-medium tracking-[-0.02em]">
            Two clicks between you and a reviewer that never sleeps.
          </p>
          <p className="font-mono text-[15px] text-muted-foreground">Fewer, better comments on every pull request.</p>
          <div className="flex flex-wrap justify-center gap-3 pt-1">
            <span className="rounded-sm border border-foreground/40 px-2 py-0.5 text-[13px]">Free starter credits</span>
            <span className="rounded-sm border border-foreground/40 px-2 py-0.5 text-[13px]">No card required</span>
          </div>
        </div>
      </section>

      <section className="flex flex-col bg-card px-6 py-8 sm:px-10">
        <Brand className="text-base font-medium lg:hidden" />
        <div className="mx-auto flex w-full max-w-[300px] flex-1 flex-col justify-center gap-6 py-12">
          <div className="flex flex-col gap-1.5 text-center">
            <h1 className="text-[22px] leading-7 font-medium tracking-tight">Sign in to HootPR</h1>
            <p className="text-[15px] text-muted-foreground">Welcome back — let&apos;s review some code.</p>
          </div>
          {error ? (
            <Alert variant="destructive" role="alert">
              <CircleAlert aria-hidden />
              <AlertDescription>{ERRORS[error] ?? "Sign-in failed. Please try again."}</AlertDescription>
            </Alert>
          ) : null}
          <ProviderButtons next={safeNext(next)} tone="outline" className="sm:flex-col" />
          <p className="text-center text-[13px] text-muted-foreground">
            Use the account that owns your repositories. You can link the other provider later.
          </p>
        </div>
        <p className="mx-auto max-w-[320px] text-center text-[12px] leading-5 text-faint">
          HootPR only accesses the repositories you install it on.{" "}
          <Link href="/" className="text-primary hover:underline">
            Learn more
          </Link>
        </p>
      </section>
    </main>
  );
}
