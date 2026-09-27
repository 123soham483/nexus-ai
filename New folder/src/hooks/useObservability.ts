import { useQuery } from '@tanstack/react-query'
import { observability } from '@/lib/api'
import type { TraceFilters } from '@/components/trace/TraceFilter'

export function useTraces(filters: TraceFilters) {
  return useQuery({
    queryKey: ['traces', filters.taskId, filters.eventType, filters.agentType],
    queryFn: () =>
      observability.traces({
        task_id: filters.taskId || undefined,
        event_type: filters.eventType || undefined,
        agent_type: filters.agentType || undefined,
      }),
    select: (res) => res.data,
  })
}
