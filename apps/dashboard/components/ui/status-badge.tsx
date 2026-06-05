import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const statusBadgeVariants = cva(
  'inline-flex items-center gap-1 rounded px-1.5 text-[9px] font-medium',
  {
    variants: {
      variant: {
        ok: 'bg-success/20 text-success',
        warning: 'bg-warning/20 text-warning',
        error: 'bg-destructive/20 text-destructive',
        inactive: 'bg-secondary text-muted-foreground',
        pending: 'bg-warning/20 text-warning',
        live: 'bg-success/20 text-success',
      },
      size: {
        sm: 'h-4 text-[8px]',
        default: 'h-5 text-[9px]',
      },
      pulse: {
        true: '',
        false: '',
      },
    },
    defaultVariants: {
      variant: 'inactive',
      size: 'default',
      pulse: false,
    },
  }
)

export interface StatusBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof statusBadgeVariants> {
  dot?: boolean
}

export function StatusBadge({
  className,
  variant,
  size,
  pulse,
  dot = false,
  children,
  ...props
}: StatusBadgeProps) {
  const dotColor = {
    ok: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-destructive',
    inactive: 'bg-muted-foreground',
    pending: 'bg-warning',
    live: 'bg-success',
  }

  return (
    <span
      className={cn(statusBadgeVariants({ variant, size, pulse }), className)}
      {...props}
    >
      {dot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            dotColor[variant || 'inactive'],
            pulse && 'animate-pulse'
          )}
        />
      )}
      {children}
    </span>
  )
}
