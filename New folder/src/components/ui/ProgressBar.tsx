import { cn } from '@/lib/utils'

export interface ProgressBarProps {
  value: number
  max?: number
  className?: string
  barClassName?: string
  /** 0-100 threshold where the bar turns amber/red (relative to max). */
  warnAt?: number
  dangerAt?: number
}

export function ProgressBar({ value, max = 100, className, barClassName, warnAt, dangerAt }: ProgressBarProps) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0
  const color =
    (dangerAt != null && pct >= dangerAt) || (warnAt != null && pct >= warnAt)
      ? pct >= (dangerAt ?? Infinity)
        ? 'var(--status-error)'
        : 'var(--status-warning)'
      : 'var(--status-success)'

  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-elevated', className)}>
      <div
        className={cn('h-full rounded-full transition-all duration-500', barClassName)}
        style={{ width: `${pct}%`, background: color }}
      />
    </div>
  )
}
