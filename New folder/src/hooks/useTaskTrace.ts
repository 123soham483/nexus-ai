import { useQuery } from '@tanstack/react-query'
import { tasks } from '@/lib/api'

export function useTaskTrace(taskId: string | undefined) {
  return useQuery({
    queryKey: ['task-trace', taskId],
    queryFn: () => tasks.trace(taskId!),
    enabled: !!taskId,
    select: (res) => res.data,
  })
}

export function useTaskCostRecords(taskId: string | undefined) {
  return useQuery({
    queryKey: ['task-cost', taskId],
    queryFn: () => tasks.cost(taskId!),
    enabled: !!taskId,
    select: (res) => res.data,
  })
}
