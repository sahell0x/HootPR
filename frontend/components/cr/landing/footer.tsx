import Link from "next/link";
import { OwlMark } from "@/components/brand";
import { CONTAINER } from "@/components/cr/landing/shared";
import { cn } from "@/lib/utils";

const COLUMNS: { heading: string; links: { label: string; href: string }[] }[] = [
  {
    heading: "Product",
    links: [
      { label: "Pull request reviews", href: "#review" },
      { label: "Walkthroughs", href: "#walkthrough" },
      { label: "Change Stack", href: "#change-stack" },
      { label: "Security", href: "#security" },
    ],
  },
  {
    heading: "Resources",
    links: [
      { label: "How it works", href: "#more" },
      { label: "Context", href: "#context" },
    ],
  },
  {
    heading: "Account",
    links: [
      { label: "Log in", href: "/login" },
      { label: "Get started", href: "/login" },
    ],
  },
];

// Placeholder profile URLs — replace with HootPR's real accounts.
const SOCIAL = [
  {
    label: "GitHub",
    href: "https://github.com/",
    path: "M12 .5C5.73.5.5 5.73.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.53-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.47.11-3.06 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.77.11 3.06.74.8 1.19 1.83 1.19 3.09 0 4.42-2.7 5.39-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5Z",
  },
  {
    label: "X",
    href: "https://x.com/",
    path: "M18.24 2.25h3.31l-7.23 8.26 8.5 11.24h-6.66l-5.21-6.82-5.97 6.82H1.67l7.73-8.84L1.25 2.25h6.83l4.71 6.23 5.45-6.23Zm-1.16 17.52h1.83L7.08 4.13H5.12l11.96 15.64Z",
  },
  {
    label: "LinkedIn",
    href: "https://www.linkedin.com/",
    path: "M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28ZM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13ZM7.12 20.45H3.56V9h3.56v11.45ZM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0Z",
  },
];

export function LandingFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t">
      <div className={cn(CONTAINER, "pt-16 md:pt-20")}>
        <div className="flex items-center justify-between gap-4">
          <Link href="/" aria-label="HootPR home" className="inline-flex">
            <OwlMark className="size-8" />
          </Link>
          <ul className="-mr-[9px] flex items-center gap-1" aria-label="HootPR on social media">
            {SOCIAL.map((s) => (
              <li key={s.label}>
                <a
                  href={s.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`HootPR on ${s.label}`}
                  className="grid size-9 place-items-center rounded-sm text-foreground/75 transition-colors hover:bg-white/[0.04] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none"
                >
                  <svg viewBox="0 0 24 24" className="size-[18px]" fill="currentColor" aria-hidden>
                    <path d={s.path} />
                  </svg>
                </a>
              </li>
            ))}
          </ul>
        </div>

        <nav aria-label="Footer" className="mt-14 grid grid-cols-2 gap-x-8 gap-y-12 sm:grid-cols-3 lg:grid-cols-5">
          {COLUMNS.map((col) => (
            <div key={col.heading}>
              <p className="font-mono text-[12px] tracking-[0.02em] text-primary uppercase">{col.heading}</p>
              <ul className="mt-5 flex flex-col gap-3.5">
                {col.links.map((l) => (
                  <li key={l.label}>
                    {l.href.startsWith("/") ? (
                      <Link href={l.href} className="text-[16px] text-foreground/85 transition-colors hover:text-foreground">
                        {l.label}
                      </Link>
                    ) : (
                      <a href={l.href} className="text-[16px] text-foreground/85 transition-colors hover:text-foreground">
                        {l.label}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div className="col-span-2 sm:col-span-3 lg:col-span-2 lg:justify-self-end">
            <p className="max-w-[34ch] text-[15px] leading-6 text-muted-foreground lg:text-right">
              AI review for GitHub pull requests and GitLab merge requests. Tools first, then agents, then a judge.
            </p>
          </div>
        </nav>

        {/* Outlined wordmark, fading out toward the bottom edge. */}
        <div
          aria-hidden
          className="mt-16 overflow-hidden select-none md:mt-24"
          style={{
            maskImage: "linear-gradient(to bottom, black 35%, transparent 95%)",
            WebkitMaskImage: "linear-gradient(to bottom, black 35%, transparent 95%)",
          }}
        >
          <svg viewBox="0 0 1000 250" className="block h-auto w-full" preserveAspectRatio="xMidYMid meet">
            <defs>
              <linearGradient id="footer-wm" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#7a3a1c" />
                <stop offset="55%" stopColor="#c2481a" />
                <stop offset="100%" stopColor="#ff570a" />
              </linearGradient>
            </defs>
            <text
              x="500"
              y="218"
              textAnchor="middle"
              textLength="1000"
              lengthAdjust="spacing"
              fontSize="270"
              fontWeight="500"
              fill="#141116"
              stroke="url(#footer-wm)"
              strokeWidth="2.4"
              paintOrder="stroke"
              style={{ fontFamily: "var(--font-body), var(--font-sans), ui-sans-serif, system-ui, sans-serif" }}
            >
              HootPR
            </text>
          </svg>
        </div>

        <div className="flex flex-col gap-3 border-t py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <span>© {year} HootPR</span>
          <span className="font-mono text-[12px] text-faint">Code reviews for GitHub and GitLab</span>
        </div>
      </div>
    </footer>
  );
}
