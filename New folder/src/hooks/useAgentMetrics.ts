import { useQuery } from '@tanstack/react-query'
import { agents, observability } from '@/lib/api'

export function useAgentMetrics() {
  return useQuery({
    queryKey: ['agent-metrics'],
    queryFn: () => agents.list(),
    select: (res) => res.data,
  })
}

export function useQualityMetrics() {
  return useQuery({
    queryKey: ['quality-metrics'],
    queryFn: () => observability.qualityMetrics(),
    select: (res) => res.data,
  })
}
