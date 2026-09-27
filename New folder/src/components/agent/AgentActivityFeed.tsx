import { useEffect, useRef } from 'react'
import { Terminal } from 'lucide-react'
import { cn, formatClock, getAgentMeta, truncate } from '@/lib/utils'
import { describeEvent, eventStyle } from '@/lib/events'
import type { TraceEvent } from '@/types/trace'

export interface AgentActivityFeedProps {
  events: TraceEvent[]
  running?: boolean
  maxHeight?: number
  className?: string
  emptyText?: string
  /** Optional resolver that renders a task goal preview per row (dashboard). */
  goalFor?: (taskId: string) => string | undefined
}

/**
 * The signature NexusAI element — a terminal-style, color-coded, auto-scrolling
 * log of everything the agents are doing, streamed over WebSocket.
 */
export function AgentActivityFeed({
  events,
  running = false,
  maxHeight = 400,
  className,
  emptyText = 'No activity yet — agents will appear here as they start.',
  goalFor,
}: AgentActivityFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [events.length])

  return (
    <div
      className={cn('overflow-y-auto rounded-lg border border-border bg-base/80 font-mono text-xs', className)}
      style={{ maxHeight }}
    >
      {events.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
          <Terminal className="h-5 w-5 text-text-muted" />
          <p className="font-sans text-text-muted">{emptyText}</p>
        </div>
      ) : (
        <div className="p-2.5">
          {events.map((event) => {
            const style = eventStyle(event.event_type)
            const agent = event.agent_type
            return (
              <div
                key={event.id}
                className="flex items-baseline gap-2.5 border-b border-border/40 px-1 py-[5px] last:border-0 hover:bg-elevated/40"
              >
                <span className="shrink-0 tabular-nums text-text-muted">{formatClock(event.timestamp)}</span>
                <span
                  className="shrink-0 rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide"
                  style={{ color: agent ? getAgentMeta(agent).color : style.color, background: agent ? getAgentMeta(agent).soft : 'transparent' }}
                >
                  {agent ?? event.event_type.replace(/_/g, ' ')}
                </span>
                <span className="min-w-0 flex-1 text-text-secondary" style={{ color: style.color }}>
                  {describeEvent(event)}
                </span>
                {goalFor?.(event.task_id) && (
                  <span className="hidden shrink-0 max-w-[200px] truncate text-[11px] text-text-muted sm:inline">
                    “{truncate(goalFor(event.task_id), 42)}”
                  </span>
                )}
              </div>
            )
          })}
          {running && (
            <div className="flex items-center gap-2 px-1 py-1.5 text-text-muted">
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-brand" />
              <span>streaming live…</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  )
}
