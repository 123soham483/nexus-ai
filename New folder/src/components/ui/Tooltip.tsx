import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface TooltipProps {
  label: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}

export function Tooltip({ label, children, side = 'top', className }: TooltipProps) {
  const pos = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
    left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
    right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
  }[side]

  return (
    <span className={cn('group relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-40 whitespace-nowrap rounded-md border border-border bg-elevated px-2 py-1 text-xs text-text-primary opacity-0 shadow-card transition-opacity duration-150 group-hover:opacity-100',
          pos,
        )}
      >
        {label}
      </span>
    </span>
  )
}
