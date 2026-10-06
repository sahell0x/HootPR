import Link from "next/link";
import { cn } from "@/lib/utils";

export function OwlMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-6", className)} aria-hidden>
      <path d="M4 9 L8 3 L12 7 L20 7 L24 3 L28 9 Q30 20 22 28 L10 28 Q2 20 4 9 Z" className="fill-primary" />
      <circle cx="11.5" cy="14" r="4.6" className="fill-background" />
      <circle cx="20.5" cy="14" r="4.6" className="fill-background" />
      <circle cx="11.5" cy="14" r="2" className="fill-primary" />
      <circle cx="20.5" cy="14" r="2" className="fill-primary" />
      <path d="M14.3 19.5 L16 22.5 L17.7 19.5 Z" className="fill-background" />
    </svg>
  );
}

export function Brand({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link
      href={href}
      className={cn("flex items-center gap-2 text-[15px] font-medium tracking-tight text-foreground", className)}
    >
      <OwlMark />
      HootPR
    </Link>
  );
}
