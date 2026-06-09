import type { ComponentProps } from "react"

import { cn } from "@/lib/utils"

export const fieldLabelClassName =
  "inline-flex items-center gap-1 text-xs font-medium text-muted-foreground"

export const fieldControlClassName =
  "w-full rounded-md border border-field-border bg-field text-sm text-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.04)] outline-none transition placeholder:text-muted-foreground/70 hover:border-cockpit-accent-border hover:bg-field/95 focus-visible:border-cockpit-accent-border focus-visible:ring-2 focus-visible:ring-cockpit-accent-border/35 disabled:cursor-not-allowed disabled:border-border/80 disabled:bg-surface-inset/70 disabled:text-muted-foreground disabled:opacity-80 aria-invalid:border-cockpit-risk aria-invalid:ring-2 aria-invalid:ring-cockpit-risk/25"

function Field({ className, ...props }: ComponentProps<"div">) {
  return <div data-slot="field" className={cn("space-y-1.5 text-sm", className)} {...props} />
}

function FieldLabel({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      data-slot="field-label"
      className={cn(fieldLabelClassName, className)}
      {...props}
    />
  )
}

function FieldMessage({
  className,
  tone = "muted",
  ...props
}: ComponentProps<"span"> & { tone?: "muted" | "error" | "success" }) {
  return (
    <span
      data-slot="field-message"
      className={cn(
        "block text-xs",
        tone === "error" && "text-cockpit-risk",
        tone === "success" && "text-success",
        tone === "muted" && "text-muted-foreground",
        className,
      )}
      {...props}
    />
  )
}

function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      data-slot="input"
      className={cn(fieldControlClassName, "h-8 px-2", className)}
      {...props}
    />
  )
}

function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      data-slot="select"
      className={cn(fieldControlClassName, "h-8 px-2", className)}
      {...props}
    />
  )
}

function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(fieldControlClassName, "min-h-28 resize-y px-3 py-2", className)}
      {...props}
    />
  )
}

export { Field, FieldLabel, FieldMessage, Input, Select, Textarea }
