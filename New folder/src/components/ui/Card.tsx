import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: ReactNode
  action?: ReactNode
  padded?: boolean
}

export function Card({ title, action, padded = true, className, children, ...props }: CardProps) {
  return (
    <div className={cn('card', className)} {...props}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          {action}
        </div>
      )}
      <div className={cn(padded && 'p-4')}>{children}</div>
    </div>
  )
}
