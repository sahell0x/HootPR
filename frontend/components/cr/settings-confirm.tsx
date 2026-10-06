"use client";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";

/** Styled confirmation dialog for destructive settings actions (replaces `window.confirm`). */
export function ConfirmAction({ trigger, title, description, confirmLabel, onConfirm, destructive = true }: {
  trigger: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  destructive?: boolean;
}) {
  return (
    <Dialog>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>
        <DialogFooter className="rounded-b-md">
          <DialogClose asChild><Button variant="outline" size="sm">Cancel</Button></DialogClose>
          <DialogClose asChild>
            <Button size="sm" variant={destructive ? "destructive" : "default"} onClick={onConfirm}>{confirmLabel}</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
