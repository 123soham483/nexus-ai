import { useNavigate } from 'react-router-dom'
import { ArrowRight, Clock, Wallet } from 'lucide-react'
import { AgentAvatar } from '@/components/agent/AgentAvatar'
import { TaskStatusBadge } from '@/components/task/TaskStatusBadge'
import { cn, formatCost, formatDuration, formatRelative, truncate } from '@/lib/utils'
import type { Task } from '@/types/task'

export function TaskCard({ task }: { task: Task }) {
  const navigate = useNavigate()
  const running = task.status === 'running' || task.status === 'routing'

  return (
    <button
      onClick={() => navigate(`/tasks/${task.id}`)}
      className={cn(
        'card group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:border-border/80',
        running && 'animate-border-pulse',
        task.status === 'failed' && 'border-l-error/60',
        task.status === 'completed' && 'border-l-success/40',
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-text-primary group-hover:text-brand-light">
          {truncate(task.goal, 80)}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
          <TaskStatusBadge status={task.status} />
          <span className="flex items-center gap-1">
            <Wallet className="h-3 w-3" />
            <span className="tabular-nums">{formatCost(task.actual_cost_usd)}</span>
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            <span className="tabular-nums">{task.duration_seconds != null ? formatDuration(task.duration_seconds) : '—'}</span>
          </span>
          <span>{formatRelative(task.created_at)}</span>
        </div>
      </div>

      {task.agents_spawned.length > 0 && (
        <div className="hidden shrink-0 items-center sm:flex">
          {task.agents_spawned.slice(0, 4).map((a) => (
            <AgentAvatar key={a} agentType={a} size="sm" className="-ml-1.5 first:ml-0 ring-2 ring-surface" />
          ))}
          {task.agents_spawned.length > 4 && (
            <span className="-ml-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-elevated text-[10px] font-medium text-text-secondary ring-2 ring-surface">
              +{task.agents_spawned.length - 4}
            </span>
          )}
        </div>
      )}

      <ArrowRight className="h-4 w-4 shrink-0 text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-brand-light" />
    </button>
  )
}
