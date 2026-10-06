"use client";
import { useParams } from "next/navigation";

/** The `[org]` route segment of `/o/{slug}/...` pages. */
export function useOrgSlug(): string {
  return useParams<{ org: string }>().org;
}
