import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { memory } from '@/lib/api'
import { apiErrorMessage } from '@/lib/utils'

export function useMemorySearch(query: string, enabled: boolean) {
  return useQuery({
    queryKey: ['memory-search', query],
    queryFn: () => memory.search(query, 10),
    enabled: enabled && query.trim().length > 0,
    select: (res) => res.data,
  })
}

export function useFailurePatterns() {
  return useQuery({
    queryKey: ['memory-failures'],
    queryFn: () => memory.failures(),
    select: (res) => res.data,
  })
}

export function useClearMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => memory.clear(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memory-search'] })
      void qc.invalidateQueries({ queryKey: ['memory-failures'] })
      toast.success('Memory cleared')
    },
    onError: (err) => {
      // In live mode the API has no delete endpoint, so this reports honestly
      // instead of leaving the user with a silently-stuck modal.
      toast.error(apiErrorMessage(err, 'Could not clear memory.'))
    },
  })
}
