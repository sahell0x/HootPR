"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Brain,
  ChevronDown,
  Layers,
  Mail,
  Menu,
  MessageSquareCode,
  ShieldCheck,
  Sparkles,
  X,
  type LucideIcon,
} from "lucide-react";
import { OwlMark } from "@/components/brand";
import { CONTAINER } from "@/components/cr/landing/shared";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "#review", label: "Review" },
  { href: "#change-stack", label: "Change Stack" },
  { href: "#security", label: "Security" },
  { href: "#context", label: "Context" },
  { href: "#more", label: "How it works" },
];

const PRODUCT: { href: string; icon: LucideIcon; title: string; body: string }[] = [
  { href: "#review", icon: MessageSquareCode, title: "Pull request review", body: "Walkthrough, inline findings and fixes" },
  { href: "#change-stack", icon: Layers, title: "Change Stack", body: "Read a diff as layers, then merge" },
  { href: "#security", icon: ShieldCheck, title: "Security", body: "Scanners run in a sandbox first" },
  { href: "#context", icon: Brain, title: "Learnings", body: "Reply once, applied per repository" },
  { href: "#more", icon: Sparkles, title: "Finishing touches", body: "Docstrings and unit tests on request" },
  { href: "#more", icon: Mail, title: "Reports", body: "Scheduled summaries in your inbox" },
];

function ProductMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const enter = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const leave = () => {
    closeTimer.current = setTimeout(() => setOpen(false), 120);
  };

  return (
    <div ref={ref} className="relative" onMouseEnter={enter} onMouseLeave={leave}>
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1 transition-colors hover:text-foreground",
          open && "text-foreground",
        )}
      >
        Product
        <ChevronDown className={cn("size-3.5 transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>
      <div
        className={cn(
          "absolute top-full left-1/2 z-30 w-[560px] -translate-x-1/2 pt-4 transition-[opacity,translate] duration-200",
          open ? "visible translate-y-0 opacity-100" : "invisible -translate-y-1 opacity-0",
        )}
      >
        <div className="grid grid-cols-2 gap-1 rounded-md border bg-popover/95 p-2 shadow-2xl shadow-black/50 backdrop-blur-xl">
          {PRODUCT.map((p) => (
            <a
              key={p.title}
              href={p.href}
              onClick={() => setOpen(false)}
              className="group flex items-start gap-3 rounded-sm p-3 transition-colors hover:bg-accent"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-sm border bg-background text-muted-foreground transition-colors group-hover:border-primary/40 group-hover:text-primary">
                <p.icon className="size-4" aria-hidden />
              </span>
              <span className="flex flex-col gap-0.5">
                <span className="text-[14px] font-medium text-foreground">{p.title}</span>
                <span className="text-[13px] leading-snug text-muted-foreground">{p.body}</span>
              </span>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}

export function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [sheet, setSheet] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!sheet) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSheet(false);
    const onResize = () => window.innerWidth >= 1024 && setSheet(false);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
      document.body.style.overflow = prev;
    };
  }, [sheet]);

  const solid = scrolled || sheet;

  return (
    <header
      className={cn(
        "sticky top-0 z-40 border-b transition-[background-color,border-color,backdrop-filter] duration-300",
        // No backdrop-filter while the sheet is open: it would become the fixed sheet's containing block.
        sheet
          ? "border-border bg-background"
          : solid
            ? "border-border/70 bg-background/80 backdrop-blur-xl backdrop-saturate-150"
            : "border-transparent bg-transparent",
      )}
    >
      <div className={cn(CONTAINER, "flex h-16 items-center gap-6")}>
        <Link href="/" className="flex shrink-0 items-center gap-2.5 text-[20px] font-semibold tracking-[-0.02em]">
          <OwlMark className="size-7" />
          HootPR
        </Link>

        <nav aria-label="Landing" className="hidden flex-1 items-center justify-center gap-7 text-[15px] text-muted-foreground lg:flex">
          <ProductMenu />
          {LINKS.map((l) => (
            <a key={l.href + l.label} href={l.href} className="transition-colors hover:text-foreground">
              {l.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto hidden items-center gap-2 lg:flex">
          <Link href="/login" className={cn(buttonVariants({ variant: "outline" }), "h-9 bg-transparent px-3.5 text-[14px]")}>
            Log in
          </Link>
          <Link href="/login" className={cn(buttonVariants({ variant: "inverse" }), "h-9 px-3.5 text-[14px]")}>
            Get started <ArrowRight aria-hidden />
          </Link>
        </div>

        <button
          type="button"
          className="ml-auto grid size-10 place-items-center rounded-sm text-foreground transition-colors hover:bg-accent lg:hidden"
          aria-label={sheet ? "Close menu" : "Open menu"}
          aria-expanded={sheet}
          aria-controls="landing-sheet"
          onClick={() => setSheet((s) => !s)}
        >
          {sheet ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
        </button>
      </div>

      <div
        id="landing-sheet"
        className={cn(
          "fixed inset-x-0 top-16 bottom-0 z-40 overflow-y-auto border-t bg-background transition-[opacity,visibility] duration-200 lg:hidden",
          sheet ? "visible opacity-100" : "invisible opacity-0",
        )}
      >
        <div className={cn(CONTAINER, "flex min-h-full flex-col gap-8 py-6")}>
          <div className="flex flex-col">
            <p className="eyebrow mb-2">Product</p>
            {PRODUCT.slice(0, 4).map((p) => (
              <a
                key={p.title}
                href={p.href}
                onClick={() => setSheet(false)}
                className="flex items-center gap-3 border-b py-3.5"
              >
                <span className="grid size-8 place-items-center rounded-sm border bg-card text-muted-foreground">
                  <p.icon className="size-4" aria-hidden />
                </span>
                <span className="flex flex-col">
                  <span className="text-[16px] font-medium">{p.title}</span>
                  <span className="text-[13px] text-muted-foreground">{p.body}</span>
                </span>
              </a>
            ))}
            <a href="#more" onClick={() => setSheet(false)} className="border-b py-3.5 text-[16px] font-medium">
              How it works
            </a>
          </div>
          <div className="mt-auto flex flex-col gap-2.5 pb-4">
            <Link href="/login" className={cn(buttonVariants({ variant: "inverse" }), "h-11 w-full text-[15px]")}>
              Get started <ArrowRight aria-hidden />
            </Link>
            <Link href="/login" className={cn(buttonVariants({ variant: "outline" }), "h-11 w-full bg-transparent text-[15px]")}>
              Log in
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}
