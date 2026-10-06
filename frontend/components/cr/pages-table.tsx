"use client";
import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export type SortState<K extends string> = { key: K; dir: SortDir } | null;

/** Click cycles a column: asc → desc → off. Returns the `sorted` prop for SortableHead plus a toggle. */
export function useSort<K extends string>(initial: SortState<K> = null) {
  const [sort, setSort] = useState<SortState<K>>(initial);
  const toggle = (key: K) =>
    setSort((s) => (s?.key !== key ? { key, dir: "asc" } : s.dir === "asc" ? { key, dir: "desc" } : null));
  const sorted = (key: K): SortDir | false => (sort?.key === key ? sort.dir : false);
  return { sort, toggle, sorted };
}

/** Sort already-loaded rows client-side; `get` maps a row to a comparable value per key. */
export function sortRows<T, K extends string>(rows: T[], sort: SortState<K>, get: (row: T, key: K) => string | number | null) {
  if (!sort) return rows;
  const mul = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = get(a, sort.key);
    const y = get(b, sort.key);
    if (x === y) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    return (x < y ? -1 : 1) * mul;
  });
}

/** Client-side pagination over loaded rows, feeding TablePagination. */
export function usePaged<T>(rows: T[], initialSize = 10) {
  const [page, setPage] = useState(1);
  const [pageSize, setSize] = useState(initialSize);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const current = Math.min(page, pageCount);
  const pageRows = useMemo(() => rows.slice((current - 1) * pageSize, current * pageSize), [rows, current, pageSize]);
  return {
    page: current,
    pageCount,
    pageSize,
    pageRows,
    onPage: setPage,
    onPageSize: (n: number) => {
      setSize(n);
      setPage(1);
    },
  };
}

export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
