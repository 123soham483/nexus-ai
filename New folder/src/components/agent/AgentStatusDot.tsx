import { cn, getAgentMeta } from '@/lib/utils'
import type { AgentRunStatus } from '@/types/agent'

const STATUS_COLOR: Record<AgentRunStatus, string> = {
  waiting: 'var(--text-muted)',
  running: 'var(--brand-primary)',
  done: 'var(--status-success)',
  failed: 'var(--status-error)',
}

export interface AgentStatusDotProps {
  status?: AgentRunStatus
  agentType?: string
  className?: string
  /** Show a pulsing ring around running dots. */
  pulse?: boolean
}

export function AgentStatusDot({ status = 'waiting', agentType, className, pulse }: AgentStatusDotProps) {
  const color = agentType ? getAgentMeta(agentType).color : STATUS_COLOR[status]
  const isRunning = status === 'running'

  return (
    <span className={cn('relative inline-flex h-2 w-2', className)}>
      {isRunning && pulse && (
        <span
          className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
          style={{ background: color }}
        />
      )}
      <span
        className={cn('relative inline-flex h-2 w-2 rounded-full', isRunning && 'animate-pulse-dot')}
        style={{ background: color }}
      />
    </span>
  )
}
