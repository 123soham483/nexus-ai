import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { tasks } from '@/lib/api'
import type { TaskCreate } from '@/types/task'

export function useTasksList(params?: { status?: string }) {
  return useQuery({
    queryKey: ['tasks', params?.status ?? 'all'],
    queryFn: () => tasks.list({ ...params, limit: 500 }),
    select: (res) => res.data,
  })
}

export function useTask(id: string | undefined) {
  return useQuery({
    queryKey: ['task', id],
    queryFn: () => tasks.get(id!),
    enabled: !!id,
    select: (res) => res.data,
  })
}

export function useCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TaskCreate) => tasks.create(data),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      qc.setQueryData(['task', res.data.id], res)
    },
  })
}

export function useCancelTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => tasks.cancel(id),
    onSuccess: (_res, id) => {
      void qc.invalidateQueries({ queryKey: ['task', id] })
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      toast.success('Task cancelled')
    },
  })
}
