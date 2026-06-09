import type { ComponentProps } from "react"

import { cn } from "@/lib/utils"

function PanelSurface({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="panel-surface"
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-field-border/55 bg-surface-panel text-card-foreground shadow-[0_0_0_1px_rgb(255_255_255/0.03),0_16px_36px_rgb(0_0_0/0.22)]",
        className,
      )}
      {...props}
    />
  )
}

function PanelHeader({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="panel-header"
      className={cn(
        "shrink-0 border-b border-border/80 bg-surface-panel-raised/70 px-4 py-3",
        className,
      )}
      {...props}
    />
  )
}

function PanelBody({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="panel-body"
      className={cn("min-h-0 flex-1 overflow-auto p-4", className)}
      {...props}
    />
  )
}

function MetricSurface({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="metric-surface"
      className={cn(
        "h-full min-h-24 overflow-hidden rounded-lg border border-field-border/55 bg-surface-panel-raised p-4 shadow-[inset_0_1px_0_rgb(255_255_255/0.04),0_10px_24px_rgb(0_0_0/0.18)]",
        className,
      )}
      {...props}
    />
  )
}

function NestedSurface({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="nested-surface"
      className={cn(
        "rounded-md border border-border/90 bg-surface-inset shadow-[inset_0_1px_0_rgb(255_255_255/0.03)]",
        className,
      )}
      {...props}
    />
  )
}

export { MetricSurface, NestedSurface, PanelBody, PanelHeader, PanelSurface }
