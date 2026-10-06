import { ShellErrorFrame, ShellErrorLink, ShellErrorPanel } from "@/components/cr/shell-error";

export default function NotFound() {
  return (
    <ShellErrorFrame>
      <ShellErrorPanel
        code="404"
        title="This page could not be found."
        description="The link may be wrong, or the page was moved."
        actions={
          <>
            <ShellErrorLink href="/orgs" primary>
              Go to your organizations
            </ShellErrorLink>
            <ShellErrorLink href="/">Home</ShellErrorLink>
          </>
        }
      />
    </ShellErrorFrame>
  );
}
