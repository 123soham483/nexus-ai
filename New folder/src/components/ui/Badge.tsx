import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

type Tone = 'neutral' | 'brand' | 'success' | 'warning' | 'error' | 'info'

const TONES: Record<Tone, string> = {
  neutral: 'bg-elevated text-text-secondary border-border',
  brand: 'bg-brand/15 text-brand-light border-brand/30',
  success: 'bg-success/15 text-success border-success/30',
  warning: 'bg-warning/15 text-warning border-warning/30',
  error: 'bg-error/15 text-error border-error/30',
  info: 'bg-info/15 text-info border-info/30',
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone
  dot?: boolean
  dotColor?: string
  children?: ReactNode
}

export function Badge({ tone = 'neutral', dot, dotColor, className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        TONES[tone],
        className,
      )}
      {...props}
    >
      {dot && (
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: dotColor ?? 'currentColor' }}
        />
      )}
      {children}
    </span>
  )
}
