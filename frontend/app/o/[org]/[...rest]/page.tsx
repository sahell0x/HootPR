import { notFound } from "next/navigation";

/** Any unknown path under /o/<org>/ renders the org's in-shell not-found page. */
export default function UnknownOrgPage() {
  notFound();
}
