import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { hitl } from '@/lib/api'
import { useNotificationStore } from '@/store/notificationStore'

export function usePendingApprovals() {
  const query = useQuery({
    queryKey: ['hitl-pending'],
    queryFn: () => hitl.pending(),
    refetchInterval: 20_000,
    select: (res) => res.data,
  })

  const setHitlPendingCount = useNotificationStore((s) => s.setHitlPendingCount)
  useEffect(() => {
    setHitlPendingCount(query.data?.length ?? 0)
  }, [query.data?.length, setHitlPendingCount])

  return query
}

export function useHITLHistory() {
  return useQuery({
    queryKey: ['hitl-history'],
    queryFn: () => hitl.history(),
    select: (res) => res.data,
  })
}

function useDecisionMutation(action: 'approve' | 'reject') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (approvalId: string) =>
      action === 'approve' ? hitl.approve(approvalId) : hitl.reject(approvalId),
    onSuccess: (_res, approvalId) => {
      void qc.invalidateQueries({ queryKey: ['hitl-pending'] })
      void qc.invalidateQueries({ queryKey: ['hitl-history'] })
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      void qc.invalidateQueries({ queryKey: ['task-trace'] })
      toast.success(action === 'approve' ? 'Approval granted' : 'Approval rejected')
      void approvalId
    },
  })
}

export function useApproveApproval() {
  return useDecisionMutation('approve')
}

export function useRejectApproval() {
  return useDecisionMutation('reject')
}
