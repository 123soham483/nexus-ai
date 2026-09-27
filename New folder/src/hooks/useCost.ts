import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { cost } from '@/lib/api'
import { apiErrorMessage } from '@/lib/utils'
import type { CostPeriod } from '@/types/cost'

export function useCostHistory(period: CostPeriod) {
  return useQuery({
    queryKey: ['cost-history', period],
    queryFn: () => cost.history(period),
    select: (res) => res.data,
  })
}

export function useCostEstimate(goal: string, enabled: boolean) {
  return useQuery({
    queryKey: ['cost-estimate', goal],
    queryFn: () => cost.estimate(goal),
    enabled: enabled && goal.trim().length >= 10,
    staleTime: 60_000,
    select: (res) => res.data,
  })
}

export function useBudget() {
  return useQuery({
    queryKey: ['budget'],
    queryFn: () => cost.budget(),
    select: (res) => res.data,
  })
}

export function useCostBreakdown(taskId?: string) {
  return useQuery({
    queryKey: ['cost-breakdown', taskId ?? 'global'],
    queryFn: () => cost.breakdown(taskId),
    select: (res) => res.data,
  })
}

export function useSetBudget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (monthlyBudgetUsd: number) => cost.setBudget(monthlyBudgetUsd),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['budget'] })
      toast.success('Budget updated')
    },
    onError: (err) => {
      // The live API only exposes GET /cost/budget — report the truth.
      toast.error(apiErrorMessage(err, 'Could not update the budget.'))
    },
  })
}
