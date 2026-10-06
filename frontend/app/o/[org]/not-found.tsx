"use client";
import { ShellErrorLink, ShellErrorPanel } from "@/components/cr/shell-error";
import { useOrgSlug } from "@/lib/use-org-slug";

/** In-shell 404 for unknown pages inside an organization (sidebar and top bar stay). */
export default function OrgNotFound() {
  const slug = useOrgSlug();
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <ShellErrorPanel
        code="404"
        title="This page could not be found."
        description="It may have moved, or the link is wrong. Pick a page from the sidebar."
        actions={<ShellErrorLink href={`/o/${slug}/repos`}>Go to repositories</ShellErrorLink>}
      />
    </div>
  );
}
