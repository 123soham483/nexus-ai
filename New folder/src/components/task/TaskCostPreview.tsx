import { Sparkles } from 'lucide-react'
import { getAgentMeta, formatCost, formatPercent } from '@/lib/utils'
import type { CostEstimate } from '@/types/cost'
import type { BudgetStatus } from '@/types/cost'
import { ProgressBar } from '@/components/ui/ProgressBar'

export interface TaskCostPreviewProps {
  estimate?: CostEstimate
  loading?: boolean
  budget?: BudgetStatus
  goalLength: number
}

export function TaskCostPreview({ estimate, loading, budget, goalLength }: TaskCostPreviewProps) {
  const show = goalLength >= 10

  if (!show) return null

  if (loading || !estimate) {
    return (
      <div className="card p-4">
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Sparkles className="h-4 w-4 animate-pulse text-brand" />
          Estimating cost…
        </div>
      </div>
    )
  }

  const rows = Object.entries(estimate.breakdown)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
  const remaining = budget ? Math.max(0, budget.monthly_budget_usd - budget.current_month_spend_usd) : null

  return (
    <div className="card animate-fade-in p-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <Sparkles className="h-4 w-4 text-brand" /> Estimated Cost
        </h3>
        <p className="text-xl font-bold tabular-nums text-brand-light">{formatCost(estimate.total_usd)}</p>
      </div>

      <div className="mt-3 overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <tbody>
            {rows.map(([agent, cost]) => {
              const meta = getAgentMeta(agent)
              return (
                <tr key={agent} className="border-b border-border/50 last:border-0">
                  <td className="flex items-center gap-2 px-3 py-2">
                    <span className="h-2 w-2 rounded-full" style={{ background: meta.color }} />
                    <span className="text-text-primary">{meta.short} Agent</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-text-muted">{meta.model}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-text-secondary">{formatCost(cost)}</td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr className="bg-elevated/60">
              <td className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">Total</td>
              <td />
              <td className="px-3 py-2 text-right font-semibold tabular-nums text-text-primary">
                {formatCost(estimate.total_usd)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="mt-2 text-xs text-text-muted">Actual cost may vary ± 15%</p>

      {budget && remaining != null && (
        <div className="mt-3 rounded-lg border border-border bg-elevated/40 p-3">
          <div className="flex justify-between text-xs">
            <span className="text-text-secondary">
              {formatCost(remaining)} of {formatCost(budget.monthly_budget_usd)} remaining this month
            </span>
            <span className="tabular-nums text-text-muted">{formatPercent(budget.percentage_used)} used</span>
          </div>
          <ProgressBar
            value={budget.percentage_used}
            warnAt={70}
            dangerAt={90}
            className="mt-2"
          />
        </div>
      )}
    </div>
  )
}
