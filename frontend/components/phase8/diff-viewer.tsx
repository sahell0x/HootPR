"use client";
import type { DiffOnMount } from "@monaco-editor/react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { useEffect, useRef } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { CsFinding } from "@/lib/phase8-types";

const DiffEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.DiffEditor), {
  ssr: false,
  loading: () => <DiffSkeleton />,
});

/** Placeholder while Monaco downloads: gutter + code-line bars, so the pane does not flash blank. */
export function DiffSkeleton() {
  return (
    <div className="flex h-full w-full flex-col gap-2.5 bg-card p-3" aria-busy="true" aria-label="Loading diff">
      {Array.from({ length: 14 }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-3 w-6 shrink-0" />
          <Skeleton className="h-3" style={{ width: `${30 + ((i * 37) % 55)}%` }} />
        </div>
      ))}
    </div>
  );
}

type Editor = Parameters<DiffOnMount>[0];
type Monaco = Parameters<DiffOnMount>[1];

/** Build a Monaco theme from the app's CSS tokens (hex values in globals.css), so the diff matches the UI. */
function defineHootTheme(monaco: Monaco, dark: boolean) {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => {
    const x = css.getPropertyValue(name).trim();
    return /^#[0-9a-f]{6}$/i.test(x) ? x : fallback;
  };
  const bg = v("--card", dark ? "#1a181d" : "#ffffff");
  const fg = v("--foreground", dark ? "#efedf0" : "#201d24");
  const faint = v("--faint", dark ? "#6f6b75" : "#9a94a1");
  const border = v("--border", dark ? "#322f37" : "#ddd8e4");
  const add = v("--success", dark ? "#85f9c5" : "#008c5a");
  const del = v("--destructive", dark ? "#ff6467" : "#e54666");
  const primary = v("--primary", "#ff570a");
  monaco.editor.defineTheme("hootpr", {
    base: dark ? "vs-dark" : "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": bg,
      "editor.foreground": fg,
      "editorGutter.background": bg,
      "editorLineNumber.foreground": faint + "b3",
      "editorLineNumber.activeForeground": fg,
      "editor.lineHighlightBackground": fg + "08",
      "editor.lineHighlightBorder": "#00000000",
      "editor.selectionBackground": primary + "33",
      "editorCursor.foreground": primary,
      "editorWidget.background": v("--popover", bg),
      "editorWidget.border": border,
      "editorHoverWidget.background": v("--popover", bg),
      "editorHoverWidget.border": border,
      "diffEditor.insertedLineBackground": add + "12",
      "diffEditor.insertedTextBackground": add + "12",
      "diffEditor.removedLineBackground": del + "12",
      "diffEditor.removedTextBackground": del + "12",
      "diffEditorGutter.insertedLineBackground": add + "0d",
      "diffEditorGutter.removedLineBackground": "#00000000",
      "diffEditor.border": border,
      "diffEditor.diagonalFill": border + "80",
      "diffEditor.unchangedRegionBackground": v("--muted", bg),
      "diffEditor.unchangedRegionForeground": faint,
      "scrollbarSlider.background": fg + "1a",
      "scrollbarSlider.hoverBackground": fg + "2e",
      "scrollbarSlider.activeBackground": fg + "40",
      "scrollbar.shadow": "#00000000",
    },
  });
}

const GLYPH: Record<string, string> = {
  critical: "hp-glyph-critical",
  major: "hp-glyph-major",
  minor: "hp-glyph-minor",
  nitpick: "hp-glyph-nitpick",
};

export function DiffViewer({
  path,
  original,
  modified,
  language,
  findings,
  revealLine,
  onCursorLine,
}: {
  /** File path; each file gets its own Monaco models so switching files never disposes a model in use. */
  path?: string;
  original: string;
  modified: string;
  language: string;
  findings: CsFinding[];
  revealLine: number | null;
  onCursorLine: (line: number) => void;
}) {
  const { resolvedTheme } = useTheme();
  const ref = useRef<{ editor: Editor; monaco: Monaco } | null>(null);
  const decorations = useRef<{ clear: () => void } | null>(null);

  const decorate = () => {
    const cur = ref.current;
    if (!cur) return;
    decorations.current?.clear();
    const right = cur.editor.getModifiedEditor();
    decorations.current = right.createDecorationsCollection(
      findings
        .filter((f) => f.side !== "LEFT")
        .map((f) => ({
          range: new cur.monaco.Range(f.start_line ?? f.end_line, 1, f.end_line, 1),
          options: {
            isWholeLine: true,
            className: "hp-finding-line",
            glyphMarginClassName: GLYPH[f.severity] ?? "hp-glyph-minor",
            glyphMarginHoverMessage: { value: `**${f.severity}** · ${f.category} — ${f.title}` },
            hoverMessage: { value: `**${f.title}**\n\n${f.body}${f.suggestion ? `\n\n\`\`\`\n${f.suggestion}\n\`\`\`` : ""}` },
          },
        })),
    );
  };

  useEffect(decorate, [findings, modified]);
  useEffect(() => {
    const cur = ref.current;
    if (!cur) return;
    // next-themes flips the <html> class first; read the tokens on the next frame.
    const id = requestAnimationFrame(() => {
      defineHootTheme(cur.monaco, resolvedTheme !== "light");
      cur.monaco.editor.setTheme("hootpr");
    });
    return () => cancelAnimationFrame(id);
  }, [resolvedTheme]);
  useEffect(() => {
    if (revealLine && ref.current) {
      const right = ref.current.editor.getModifiedEditor();
      right.revealLineInCenter(revealLine);
      right.setPosition({ lineNumber: revealLine, column: 1 });
    }
  }, [revealLine]);

  return (
    <>
      <style>{`
        .hp-finding-line { background: color-mix(in oklch, var(--primary) 9%, transparent); box-shadow: inset 2px 0 0 color-mix(in oklch, var(--primary) 70%, transparent); }
        .hp-glyph-critical, .hp-glyph-major, .hp-glyph-minor, .hp-glyph-nitpick { border-radius: 9999px; margin-left: 4px; width: 10px !important; height: 10px !important; margin-top: 4px; }
        .hp-glyph-critical { background: var(--destructive); }
        .hp-glyph-major { background: var(--primary); }
        .hp-glyph-minor { background: var(--caution); }
        .hp-glyph-nitpick { background: var(--chart-3); }
      `}</style>
      <div className="hp-diff h-full">
      <DiffEditor
        height="100%"
        original={original}
        modified={modified}
        language={language}
        theme="hootpr"
        loading={<DiffSkeleton />}
        originalModelPath={path ? `inmemory://hootpr/original/${path}` : undefined}
        modifiedModelPath={path ? `inmemory://hootpr/modified/${path}` : undefined}
        keepCurrentOriginalModel
        keepCurrentModifiedModel
        beforeMount={(monaco) => defineHootTheme(monaco, resolvedTheme !== "light")}
        options={{
          readOnly: true,
          renderSideBySide: original.trim() !== "",
          glyphMargin: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 12.5,
          lineHeight: 20,
          fontFamily: "var(--font-code), ui-monospace, SFMono-Regular, Menlo, monospace",
          fontLigatures: false,
          lineNumbersMinChars: 3,
          renderLineHighlight: "line",
          renderOverviewRuler: false,
          overviewRulerBorder: false,
          hideCursorInOverviewRuler: true,
          padding: { top: 8, bottom: 8 },
          scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8, useShadows: false },
          guides: { indentation: false },
          automaticLayout: true,
        }}
        onMount={(editor, monaco) => {
          ref.current = { editor, monaco };
          decorate();
          editor.getModifiedEditor().onDidChangeCursorPosition((e) => onCursorLine(e.position.lineNumber));
        }}
      />
      </div>
    </>
  );
}
