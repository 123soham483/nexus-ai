import { cn, formatClock, getAgentMeta } from '@/lib/utils'
import { describeEvent, eventStyle } from '@/lib/events'
import type { TraceEvent as TraceEventType } from '@/types/trace'

export interface TraceEventRowProps {
  event: TraceEventType
  showTask?: boolean
  className?: string
}

export function TraceEventRow({ event, showTask, className }: TraceEventRowProps) {
  const style = eventStyle(event.event_type)
  const agent = event.agent_type ? getAgentMeta(event.agent_type) : null

  return (
    <div
      className={cn(
        'flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 border-b border-border/40 px-1 py-[5px] text-xs last:border-0 hover:bg-elevated/40',
        className,
      )}
    >
      <span className="shrink-0 tabular-nums text-text-muted">{formatClock(event.timestamp)}</span>
      {agent && (
        <span
          className="shrink-0 rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide"
          style={{ color: agent.color, background: agent.soft }}
        >
          {agent.short}
        </span>
      )}
      {showTask && <span className="shrink-0 font-mono text-[10px] text-text-muted">{event.task_id}</span>}
      <span className="min-w-0 flex-1" style={{ color: style.color }}>
        {describeEvent(event)}
      </span>
    </div>
  )
}
