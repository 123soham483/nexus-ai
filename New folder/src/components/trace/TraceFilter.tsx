import { useState } from 'react'
import { Filter, RotateCcw, Search } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { ALL_AGENT_TYPES, getAgentMeta } from '@/lib/utils'

export interface TraceFilters {
  taskId: string
  eventType: string
  agentType: string
}

export const EVENT_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All event types' },
  ...[
    'task_started', 'failure_patterns_checked', 'routing_complete', 'cost_estimated',
    'agent_spawned', 'agent_thinking', 'agent_tool_called', 'agent_tool_result',
    'agent_memory_retrieved', 'hitl_required', 'hitl_resolved', 'agent_completed',
    'hallucination_check', 'quality_check', 'learning_stored', 'task_completed', 'task_failed',
  ].map((v) => ({ value: v, label: v.replace(/_/g, ' ') })),
]

export interface TraceFilterProps {
  onApply: (filters: TraceFilters) => void
  initial?: Partial<TraceFilters>
}

export function TraceFilter({ onApply, initial }: TraceFilterProps) {
  const [filters, setFilters] = useState<TraceFilters>({
    taskId: initial?.taskId ?? '',
    eventType: initial?.eventType ?? '',
    agentType: initial?.agentType ?? '',
  })

  return (
    <div className="card p-4">
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
        <Input
          placeholder="Task ID (e.g. t_abc12345)"
          value={filters.taskId}
          onChange={(e) => setFilters((f) => ({ ...f, taskId: e.target.value }))}
          leftIcon={<Search className="h-4 w-4" />}
        />
        <Select
          value={filters.eventType}
          onChange={(e) => setFilters((f) => ({ ...f, eventType: e.target.value }))}
          options={EVENT_TYPE_OPTIONS}
          placeholder="All event types"
        />
        <Select
          value={filters.agentType}
          onChange={(e) => setFilters((f) => ({ ...f, agentType: e.target.value }))}
          options={[{ value: '', label: 'All agents' }, ...ALL_AGENT_TYPES.map((a) => ({ value: a, label: getAgentMeta(a).label }))]}
          placeholder="All agents"
        />
        <div className="flex gap-2">
          <Button
            size="md"
            onClick={() =>
              onApply({
                taskId: filters.taskId.trim(),
                eventType: filters.eventType,
                agentType: filters.agentType,
              })
            }
          >
            <Filter className="h-4 w-4" /> Apply
          </Button>
          <Button
            variant="ghost"
            size="md"
            onClick={() => {
              setFilters({ taskId: '', eventType: '', agentType: '' })
              onApply({ taskId: '', eventType: '', agentType: '' })
            }}
          >
            <RotateCcw className="h-4 w-4" /> Clear
          </Button>
        </div>
      </div>
    </div>
  )
}
