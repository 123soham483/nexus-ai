import { STATUS_META, cn } from '@/lib/utils'
import type { TaskStatus } from '@/types/task'

export interface TaskStatusBadgeProps {
  status: TaskStatus
  className?: string
}

export function TaskStatusBadge({ status, className }: TaskStatusBadgeProps) {
  const meta = STATUS_META[status]
  const Icon = meta.icon
  const running = status === 'running' || status === 'routing'

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium',
        className,
      )}
      style={{
        color: meta.color,
        background: `color-mix(in srgb, ${meta.color} 12%, transparent)`,
        borderColor: `color-mix(in srgb, ${meta.color} 30%, transparent)`,
      }}
    >
      <Icon className={cn('h-3 w-3', running && 'animate-spin')} />
      {meta.label}
      {status === 'running' && <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full" style={{ background: meta.color }} />}
    </span>
  )
}
