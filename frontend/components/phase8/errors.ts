import { toast } from "sonner";
import { ApiError } from "@/lib/api";

export const toastError = (fallback: string) => (e: unknown) =>
  toast.error(e instanceof ApiError ? e.message : fallback);
