import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, ListTree } from 'lucide-react'
import { TraceEventRow } from '@/components/trace/TraceEvent'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { TaskStatusBadge } from '@/components/task/TaskStatusBadge'
import { cn, formatCost, formatDuration, idShort, truncate } from '@/lib/utils'
import type { TraceEvent } from '@/types/trace'
import type { Task } from '@/types/task'

export interface TraceTimelineProps {
  events: TraceEvent[]
  tasks?: Record<string, Task>
  defaultExpanded?: boolean
  maxHeight?: number
}

export function TraceTimeline({ events, tasks = {}, defaultExpanded = false, maxHeight }: TraceTimelineProps) {
  const groups = useMemo(() => {
    const map = new Map<string, TraceEvent[]>()
    for (const e of events) {
      const arr = map.get(e.task_id) ?? []
      arr.push(e)
      map.set(e.task_id, arr)
    }
    return [...map.entries()]
      .map(([taskId, evs]) => ({ taskId, events: evs.sort((a, b) => a.sequence_number - b.sequence_number) }))
      .sort((a, b) => {
        const lastA = a.events[a.events.length - 1]?.timestamp ?? ''
        const lastB = b.events[b.events.length - 1]?.timestamp ?? ''
        return new Date(lastB).getTime() - new Date(lastA).getTime()
      })
  }, [events])

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [allExpanded, setAllExpanded] = useState(defaultExpanded)

  if (groups.length === 0) {
    return <EmptyState icon={<ListTree className="h-6 w-6" />} title="No traces found" description="Adjust your filters or run a task to see its execution trace." />
  }

  const toggleAll = () => {
    const next = !allExpanded
    setAllExpanded(next)
    setCollapsed({})
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={toggleAll}>
          {allExpanded ? 'Collapse All' : 'Expand All'}
        </Button>
      </div>

      {groups.map((group) => {
        const task = tasks[group.taskId]
        const isCollapsed = allExpanded ? false : collapsed[group.taskId]
        const last = group.events[group.events.length - 1]
        const cost = typeof last?.event_data?.cost_usd === 'number' ? last.event_data.cost_usd : task?.actual_cost_usd
        const duration = typeof last?.event_data?.duration_seconds === 'number' ? last.event_data.duration_seconds : task?.duration_seconds

        return (
          <div key={group.taskId} className="card overflow-hidden">
            <button
              onClick={() => setCollapsed((c) => ({ ...c, [group.taskId]: !c[group.taskId] }))}
              className="flex w-full flex-wrap items-center gap-2 border-b border-border bg-elevated/30 px-4 py-2.5 text-left transition-colors hover:bg-elevated/60"
            >
              {isCollapsed ? <ChevronRight className="h-4 w-4 text-text-muted" /> : <ChevronDown className="h-4 w-4 text-text-muted" />}
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary">
                {task ? truncate(task.goal, 70) : `Task ${idShort(group.taskId)}`}
              </span>
              <span className="font-mono text-[11px] text-text-muted">{idShort(group.taskId)}</span>
              {task && <TaskStatusBadge status={task.status} />}
              {!task && <Badge tone="neutral">{group.events.length} events</Badge>}
              <span className="hidden text-xs tabular-nums text-text-muted sm:block">
                {duration != null ? formatDuration(duration) : ''}
                {cost != null ? ` · ${formatCost(cost)}` : ''}
              </span>
            </button>

            {!isCollapsed && (
              <div className={cn('p-2.5 font-mono text-xs', maxHeight && 'overflow-y-auto')} style={maxHeight ? { maxHeight } : undefined}>
                {group.events.map((e) => (
                  <TraceEventRow key={e.id} event={e} />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
