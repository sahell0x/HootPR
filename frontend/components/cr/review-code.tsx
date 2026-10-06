import { cn } from "@/lib/utils";

/** True when the text looks like a unified diff (every non-empty line starts with +, -, space or @@). */
function looksLikeDiff(lines: string[]) {
  const body = lines.filter((l) => l.length > 0);
  return body.length > 0 && body.some((l) => /^[+-]/.test(l)) && body.every((l) => /^([+\- ]|@@)/.test(l));
}

/**
 * Mono code block on bg-surface. Diff-shaped text gets red/green line tints; `accent` adds the
 * orange left rule used for suggestions (CodeRabbit's quoted-suggestion look).
 */
export function CodeBlock({
  code,
  label,
  accent = false,
  className,
}: {
  code: string;
  label?: string;
  accent?: boolean;
  className?: string;
}) {
  const lines = code.replace(/\n$/, "").split("\n");
  const diff = looksLikeDiff(lines);
  return (
    <div className={cn("overflow-hidden rounded-md border bg-surface", accent && "border-l-2 border-l-primary/70", className)}>
      {label ? (
        <div className="flex items-center justify-between border-b px-3 py-1.5">
          <span className="eyebrow">{label}</span>
          {diff ? <span className="font-mono text-[0.6875rem] text-faint">diff</span> : null}
        </div>
      ) : null}
      <pre className="overflow-x-auto py-2 font-mono text-xs leading-5">
        <code className="block min-w-fit">
          {lines.map((l, i) => {
            const add = diff && l.startsWith("+");
            const del = diff && l.startsWith("-");
            return (
              <span
                key={i}
                className={cn(
                  "block px-3 whitespace-pre",
                  add && "bg-success/10 text-success",
                  del && "bg-destructive/10 text-destructive",
                  diff && l.startsWith("@@") && "text-chart-3",
                )}
              >
                {l || " "}
              </span>
            );
          })}
        </code>
      </pre>
    </div>
  );
}
