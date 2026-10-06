"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/**
 * Lets a page take over parts of the app shell the way CodeRabbit's settings mode does:
 * - `SidebarOverride` replaces the main nav with page-specific navigation ("← Back" + sections).
 * - `TopbarTitle` replaces the breadcrumb's last segment; `TopbarActions` adds buttons on the top bar's right.
 * The shell reads the values with `useShellSlots()`.
 */
type Slots = { sidebar: ReactNode | null; title: ReactNode | null; actions: ReactNode | null };
type Ctx = Slots & { set: (key: keyof Slots, node: ReactNode | null) => void };

const ShellSlotsContext = createContext<Ctx | null>(null);

export function ShellSlotsProvider({ children }: { children: ReactNode }) {
  const [slots, setSlots] = useState<Slots>({ sidebar: null, title: null, actions: null });
  // `set` must be stable: slot effects depend on it, and a new identity per render loops forever.
  const set = useCallback(
    (key: keyof Slots, node: ReactNode | null) => setSlots((s) => (s[key] === node ? s : { ...s, [key]: node })),
    [],
  );
  const value = useMemo(() => ({ ...slots, set }), [slots, set]);
  return <ShellSlotsContext.Provider value={value}>{children}</ShellSlotsContext.Provider>;
}

export function useShellSlots(): Slots {
  const ctx = useContext(ShellSlotsContext);
  return ctx ?? { sidebar: null, title: null, actions: null };
}

function useSlot(key: keyof Slots, node: ReactNode) {
  const ctx = useContext(ShellSlotsContext);
  const set = ctx?.set;
  useEffect(() => {
    set?.(key, node);
  }, [set, key, node]);
  useEffect(() => () => set?.(key, null), [set, key]);
}

/** Rendered by a page; outside the shell (tests) it renders nothing, so callers must not rely on it for content. */
export function SidebarOverride({ children }: { children: ReactNode }) {
  useSlot("sidebar", children);
  return null;
}
export function TopbarTitle({ children }: { children: ReactNode }) {
  useSlot("title", children);
  return null;
}
export function TopbarActions({ children }: { children: ReactNode }) {
  useSlot("actions", children);
  return null;
}
