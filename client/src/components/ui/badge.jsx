import { cva } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-[0.12em]',
  {
    variants: {
      variant: {
        default: 'border-border bg-secondary text-secondary-foreground',
        accent: 'border-primary/30 bg-primary/10 text-primary',
        muted: 'border-border bg-transparent text-muted-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

function Badge({ className, variant, ...props }) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
