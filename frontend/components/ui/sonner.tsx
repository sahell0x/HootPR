"use client"

import { useTheme } from "next-themes"
import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react"

// Toasts are neutral popovers with a colored icon (CodeRabbit style), so don't pass `richColors`.
const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme()

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      icons={{
        success: (
          <CircleCheckIcon className="size-4" />
        ),
        info: (
          <InfoIcon className="size-4" />
        ),
        warning: (
          <TriangleAlertIcon className="size-4" />
        ),
        error: (
          <OctagonXIcon className="size-4" />
        ),
        loading: (
          <Loader2Icon className="size-4 animate-spin" />
        ),
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast:
            "cn-toast !font-sans !gap-2.5 !rounded-md !border-border !bg-popover !px-3.5 !py-3 !text-[13px] !text-popover-foreground !shadow-lg",
          title: "!font-medium",
          description: "!text-muted-foreground",
          icon: "!m-0",
          success: "[&_[data-icon]]:text-success",
          error: "!border-destructive/40 [&_[data-icon]]:text-destructive",
          warning: "[&_[data-icon]]:text-caution",
          info: "[&_[data-icon]]:text-primary",
          actionButton: "!rounded-sm !bg-foreground !text-background",
          cancelButton: "!rounded-sm !bg-muted !text-muted-foreground",
          closeButton: "!border-border !bg-popover !text-muted-foreground hover:!text-foreground",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
