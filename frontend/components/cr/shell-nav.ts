import {
  BookOpen,
  Building2,
  CreditCard,
  FileCode2,
  FileText,
  FolderGit2,
  GitPullRequest,
  KeyRound,
  Layers,
  LayoutDashboard,
  Settings2,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

/** Flat main navigation (CodeRabbit-style: no section labels). `href` is relative to /o/<org>/. */
export const NAV_ITEMS: NavItem[] = [
  { href: "repos", label: "Repositories", icon: FolderGit2 },
  { href: "analytics", label: "Dashboard", icon: LayoutDashboard },
  { href: "reviews", label: "Reviews", icon: GitPullRequest },
  { href: "change-stack", label: "Change Stack", icon: Layers },
  { href: "reports", label: "Reports", icon: FileText },
  { href: "learnings", label: "Learnings", icon: BookOpen },
  { href: "security", label: "Security", icon: ShieldCheck },
  { href: "config-guide", label: "Config Guide", icon: FileCode2 },
];

export const ORG_SETTINGS = { label: "Organization Settings", icon: Building2 };

export const ORG_SETTINGS_ITEMS: NavItem[] = [
  { href: "settings", label: "Configuration", icon: Settings2 },
  { href: "api-audit", label: "API Keys & Audit", icon: KeyRound },
  { href: "billing", label: "Billing", icon: CreditCard },
];

/** Optional external links; the shell hides a control when its URL is not configured. */
export const DOCS_URL = process.env.NEXT_PUBLIC_DOCS_URL || "";
export const ISSUES_URL = process.env.NEXT_PUBLIC_ISSUES_URL || "";

export function isActive(pathname: string, to: string) {
  return pathname === to || pathname.startsWith(`${to}/`);
}

export type Crumb = { label: string; href?: string };

function safeDecode(s: string) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/** "/o/x/repos/owner%2Fname/settings" → x / Repositories / owner/name / Settings. The last crumb has no href. */
export function breadcrumbs(
  pathname: string,
  orgSlug: string,
  orgName: string,
  names: Record<string, string> = {},
): Crumb[] {
  const base = `/o/${orgSlug}`;
  const crumbs: Crumb[] = [{ label: orgName, href: `${base}/repos` }];
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] !== "o" || parts.length < 3) return crumbs.map((c, i, a) => (i === a.length - 1 ? { label: c.label } : c));
  const section = parts[2] ?? "";
  const rest = parts.slice(3);
  const main = NAV_ITEMS.find((i) => i.href === section);
  const sub = ORG_SETTINGS_ITEMS.find((i) => i.href === section);
  if (main) crumbs.push({ label: main.label, href: `${base}/${main.href}` });
  else if (sub) {
    crumbs.push({ label: ORG_SETTINGS.label, href: `${base}/settings` });
    crumbs.push({ label: sub.label, href: `${base}/${sub.href}` });
  } else crumbs.push({ label: safeDecode(section) });
  // Deeper segments (a repo, a review id) have no page of their own: plain text.
  for (const seg of rest) {
    let label = names[safeDecode(seg)] ?? safeDecode(seg);
    if (label === "settings") label = "Settings";
    else if (section === "reviews" && label.length > 12) label = `${label.slice(0, 8)}…`;
    crumbs.push({ label });
  }
  const last = crumbs.length - 1;
  crumbs[last] = { label: crumbs[last]!.label };
  return crumbs;
}
