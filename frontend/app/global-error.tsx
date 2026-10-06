"use client";
import "./globals.css";

/** Last-resort boundary: replaces the root layout, so it renders its own <html> with the dark tokens. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en" className="dark">
      <body className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-4 text-center font-sans text-foreground antialiased">
        <p aria-hidden className="font-mono text-[72px] leading-none font-medium tracking-tight text-foreground/90">
          500
        </p>
        <h1 role="alert" className="mt-2 text-xl font-medium tracking-tight">
          HootPR ran into a problem.
        </h1>
        <p className="max-w-md text-sm text-muted-foreground">
          The app failed to load. Try again; if it keeps happening, reload the page.
          {error.digest ? <span className="mt-2 block font-mono text-xs text-faint">ref {error.digest}</span> : null}
        </p>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => reset()}
            className="inline-flex h-9 items-center rounded-md bg-foreground px-4 text-sm font-medium text-background hover:bg-foreground/85 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            Try again
          </button>
          {/* A full reload is intended: the root layout itself failed, so client routing may be broken. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a
            href="/"
            className="inline-flex h-9 items-center rounded-md border border-border bg-card px-4 text-sm font-medium hover:bg-subtle focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            Home
          </a>
        </div>
      </body>
    </html>
  );
}
