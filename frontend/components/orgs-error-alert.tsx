import { CircleAlert } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { loginUrl } from "@/lib/api";

// Codes from the GitHub post-install redirect (backend app/api/github_setup.py).
const MESSAGES: Record<string, string> = {
  github_identity_required:
    "Connect your GitHub account first, then reopen the installation from GitHub to link it to HootPR.",
  not_a_member: "You are not a member of that GitHub organization, so the installation was not linked.",
  installation_not_found: "GitHub could not find that installation. Please try installing again.",
  provider_error: "GitHub did not respond while linking the installation. Please try again.",
};

export function OrgsErrorAlert({ code }: { code: string | null }) {
  if (!code) return null;
  return (
    <Alert variant="destructive" role="alert">
      <CircleAlert aria-hidden />
      <AlertDescription className="flex flex-col items-start gap-3">
        <span>{MESSAGES[code] ?? "Something went wrong while linking the installation. Please try again."}</span>
        {code === "github_identity_required" ? (
          <a className={buttonVariants({ variant: "outline", size: "sm" })} href={loginUrl("github", "/orgs")}>
            Connect GitHub
          </a>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
