import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      {icon && (
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border bg-elevated text-text-secondary">
          {icon}
        </div>
      )}
      <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-text-secondary">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
