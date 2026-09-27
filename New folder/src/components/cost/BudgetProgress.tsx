import { CalendarDays, TrendingUp } from 'lucide-react'
import { formatCost, formatPercent } from '@/lib/utils'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Skeleton } from '@/components/ui/Skeleton'
import type { BudgetStatus } from '@/types/cost'

export function BudgetProgress({ budget, loading }: { budget?: BudgetStatus; loading?: boolean }) {
  if (loading || !budget) {
    return (
      <div className="card space-y-4 p-5">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-2 w-full" />
        <Skeleton className="h-4 w-56" />
      </div>
    )
  }

  const pct = budget.percentage_used
  const daysLeft = budget.days_remaining
  const projection =
    daysLeft > 0 ? budget.current_month_spend_usd * ((30 - daysLeft + 30) / Math.max(1, 30 - daysLeft)) : budget.current_month_spend_usd

  return (
    <div className="card p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-text-muted">This Month&apos;s Spending</p>
          <p className="mt-1 text-3xl font-bold tabular-nums text-text-primary">{formatCost(budget.current_month_spend_usd)}</p>
          <p className="mt-0.5 text-sm text-text-secondary">
            out of <span className="tabular-nums">{formatCost(budget.monthly_budget_usd)}</span> budget
          </p>
        </div>
        <div className="flex items-center gap-6 text-sm">
          <div className="text-center">
            <p className="text-lg font-bold tabular-nums text-text-primary">{formatPercent(pct, 1)}</p>
            <p className="text-xs text-text-muted">used</p>
          </div>
          <div className="text-center">
            <p className="flex items-center justify-center gap-1 text-lg font-bold tabular-nums text-text-primary">
              <CalendarDays className="h-4 w-4 text-text-muted" />
              {daysLeft}
            </p>
            <p className="text-xs text-text-muted">days left</p>
          </div>
        </div>
      </div>

      <ProgressBar value={pct} warnAt={70} dangerAt={90} className="mt-5 h-2.5" />

      <div className="mt-4 flex items-center gap-2 rounded-lg border border-border bg-elevated/40 px-3 py-2.5 text-sm">
        <TrendingUp className="h-4 w-4 text-brand-light" />
        <span className="text-text-secondary">
          At current rate: <span className="font-medium tabular-nums text-text-primary">on track to spend {formatCost(projection)}</span> this month
        </span>
      </div>
    </div>
  )
}
