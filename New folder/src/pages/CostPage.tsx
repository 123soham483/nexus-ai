import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Pencil, Wallet } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { Skeleton } from '@/components/ui/Skeleton'
import { BudgetProgress } from '@/components/cost/BudgetProgress'
import { CostChart } from '@/components/cost/CostChart'
import { AgentAvatar } from '@/components/agent/AgentAvatar'
import { cn, formatCost, formatDuration, formatNumber, getAgentMeta, truncate } from '@/lib/utils'
import { useBudget, useCostHistory, useCostBreakdown, useSetBudget } from '@/hooks/useCost'
import { useTasksList } from '@/hooks/useTasks'
import type { CostPeriod } from '@/types/cost'

const PERIODS: Array<{ key: CostPeriod; label: string }> = [
  { key: 'daily', label: 'Daily' },
  { key: 'weekly', label: 'Weekly' },
  { key: 'monthly', label: 'Monthly' },
]

const PIE_COLORS = ['#10B981', '#E3B341', '#22D3EE', '#F59E0B']

export function CostPage() {
  const navigate = useNavigate()
  const [period, setPeriod] = useState<CostPeriod>('daily')
  const [editBudget, setEditBudget] = useState(false)
  const [budgetInput, setBudgetInput] = useState('')
  const { data: budget, isLoading: budgetLoading } = useBudget()
  const { data: history, isLoading: historyLoading } = useCostHistory(period)
  // The recent-months summary is its own request: it must not change when the
  // chart period toggle changes.
  const { data: monthlyHistory } = useCostHistory('monthly')
  const { data: breakdown, isLoading: breakdownLoading } = useCostBreakdown()
  const { data: tasks } = useTasksList()
  const setBudget = useSetBudget()

  const expensive = useMemo(
    () =>
      [...(tasks ?? [])]
        .filter((t) => t.actual_cost_usd > 0)
        .sort((a, b) => b.actual_cost_usd - a.actual_cost_usd)
        .slice(0, 10),
    [tasks],
  )

  const maxAgentCost = Math.max(...(breakdown?.agents.map((a) => a.cost_usd) ?? [0]), 1)

  return (
    <PageWrapper>
      {/* Section A — budget overview */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <BudgetProgress budget={budget} loading={budgetLoading} />
        </div>
        <div className="card flex flex-col justify-between p-5">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-text-muted">Edit budget</p>
            <p className="mt-1 text-sm text-text-secondary">Set your monthly spending limit. Alerts fire at 70% and 90%.</p>
          </div>
          <Button
            variant="outline"
            className="mt-4 w-full"
            onClick={() => {
              setBudgetInput(budget ? String(budget.monthly_budget_usd) : '')
              setEditBudget(true)
            }}
          >
            <Pencil className="h-4 w-4" /> Edit Budget
          </Button>
          <div className="mt-4 space-y-1.5 border-t border-border pt-3">
            <p className="text-xs text-text-muted">Recent months</p>
            {(() => {
              // Real per-month totals from GET /cost/history, newest first.
              const recent = [...(monthlyHistory ?? [])].reverse().slice(0, 3)
              if (recent.length === 0) {
                return <p className="text-xs text-text-muted">No spend recorded yet.</p>
              }
              return recent.map((m) => (
                <div key={m.period} className="flex justify-between text-xs">
                  <span className="text-text-secondary">{m.period}</span>
                  <span className="tabular-nums text-text-muted">{formatCost(m.total_usd)}</span>
                </div>
              ))
            })()}
          </div>
        </div>
      </div>

      {/* Section B — period chart */}
      <div className="mt-4">
        <Card
          title="Spending Trend"
          action={
            <div className="flex rounded-lg border border-border bg-elevated/50 p-0.5">
              {PERIODS.map((p) => (
                <button
                  key={p.key}
                  onClick={() => setPeriod(p.key)}
                  className={cn(
                    'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                    period === p.key ? 'bg-brand text-[#06281c]' : 'text-text-secondary hover:text-text-primary',
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          }
        >
          {historyLoading || !history ? (
            <Skeleton className="h-[240px] w-full" />
          ) : (
            <CostChart data={history} height={240} />
          )}
        </Card>
      </div>

      {/* Sections C + D */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {/* Model breakdown */}
        <Card title="Cost by LLM Model">
          {breakdownLoading || !breakdown ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <div>
              <div className="flex items-center gap-6">
                <div className="relative h-44 w-44 shrink-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={breakdown.models}
                        dataKey="total_cost_usd"
                        nameKey="model"
                        innerRadius={52}
                        outerRadius={72}
                        paddingAngle={2}
                        stroke="var(--bg-surface)"
                      >
                        {breakdown.models.map((m, i) => (
                          <Cell key={m.model} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value: number | string, name: string) => [formatCost(Number(value)), name]}
                        contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--bg-border)', borderRadius: 8, fontSize: 12 }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-lg font-bold tabular-nums text-text-primary">{formatCost(breakdown.total_usd)}</span>
                    <span className="text-[10px] uppercase tracking-wide text-text-muted">total</span>
                  </div>
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  {breakdown.models.map((m, i) => (
                    <div key={m.model} className="flex items-center gap-2 text-sm">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      <span className="min-w-0 flex-1 truncate text-text-secondary">{m.model}</span>
                      <span className="tabular-nums text-text-primary">{m.pct}%</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-4 overflow-x-auto rounded-lg border border-border">
                <table className="w-full min-w-[420px] text-sm">
                  <thead>
                    <tr className="border-b border-border bg-elevated/40 text-left text-[11px] uppercase tracking-wide text-text-muted">
                      <th className="px-3 py-2 font-medium">Model</th>
                      <th className="px-3 py-2 text-right font-medium">Calls</th>
                      <th className="px-3 py-2 text-right font-medium">Avg Tokens</th>
                      <th className="px-3 py-2 text-right font-medium">Total Cost</th>
                      <th className="px-3 py-2 text-right font-medium">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {breakdown.models.map((m) => (
                      <tr key={m.model} className="border-b border-border/50 last:border-0">
                        <td className="px-3 py-2 text-text-primary">{m.model}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">{formatNumber(m.calls)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">{formatNumber(m.avg_tokens)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-text-primary">{formatCost(m.total_cost_usd)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">{m.pct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>

        {/* Cost by agent */}
        <Card title="Cost by Agent">
          {breakdownLoading || !breakdown ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <div className="space-y-4">
              {breakdown.agents.map((a) => {
                const meta = getAgentMeta(a.agent_type)
                return (
                  <div key={a.agent_type}>
                    <div className="mb-1.5 flex items-center justify-between text-sm">
                      <span className="flex items-center gap-2 text-text-secondary">
                        <AgentAvatar agentType={a.agent_type} size="sm" />
                        {meta.label}
                      </span>
                      <span className="tabular-nums text-text-primary">
                        {formatCost(a.cost_usd)}
                        <span className="ml-2 text-xs text-text-muted">{a.pct}%</span>
                      </span>
                    </div>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-elevated">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${(a.cost_usd / maxAgentCost) * 100}%`, background: meta.color }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      </div>

      {/* Section E — most expensive tasks */}
      <div className="mt-4">
        <Card title="Most Expensive Tasks" padded={false}>
          {!tasks ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : expensive.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-text-muted">No cost data yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b border-border bg-elevated/40 text-left text-[11px] uppercase tracking-wide text-text-muted">
                    <th className="px-4 py-2.5 font-medium">Goal</th>
                    <th className="hidden px-3 py-2.5 font-medium md:table-cell">Agents</th>
                    <th className="px-3 py-2.5 text-right font-medium">Cost</th>
                    <th className="hidden px-3 py-2.5 font-medium sm:table-cell">Duration</th>
                    <th className="px-3 py-2.5 text-right font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {expensive.map((t) => (
                    <tr
                      key={t.id}
                      onClick={() => navigate(`/tasks/${t.id}`)}
                      className="cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-elevated/40"
                    >
                      <td className="max-w-[300px] px-4 py-2.5">
                        <p className="truncate font-medium text-text-primary">{truncate(t.goal, 60)}</p>
                      </td>
                      <td className="hidden px-3 py-2.5 md:table-cell">
                        <div className="flex">
                          {t.agents_spawned.slice(0, 3).map((a) => (
                            <AgentAvatar key={a} agentType={a} size="sm" className="-ml-1.5 first:ml-0 ring-2 ring-surface" />
                          ))}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-text-primary">{formatCost(t.actual_cost_usd)}</td>
                      <td className="hidden px-3 py-2.5 text-right tabular-nums text-text-secondary sm:table-cell">
                        {t.duration_seconds != null ? formatDuration(t.duration_seconds) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <ArrowRight className="ml-auto h-4 w-4 text-text-muted" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Modal
        open={editBudget}
        onClose={() => setEditBudget(false)}
        title="Edit monthly budget"
        description="Costs are stored in USD and shown in your display currency."
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditBudget(false)}>
              Cancel
            </Button>
            <Button
              loading={setBudget.isPending}
              onClick={() => {
                const v = parseFloat(budgetInput)
                if (!Number.isNaN(v) && v > 0) {
                  setBudget.mutate(v, { onSuccess: () => setEditBudget(false) })
                }
              }}
            >
              Save budget
            </Button>
          </>
        }
      >
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-elevated text-brand-light">
            <Wallet className="h-4 w-4" />
          </span>
          <Input
            type="number"
            min="0"
            step="0.01"
            value={budgetInput}
            onChange={(e) => setBudgetInput(e.target.value)}
            placeholder="60.24"
            autoFocus
          />
        </div>
        <p className="mt-2 text-xs text-text-muted">Current: {budget ? formatCost(budget.monthly_budget_usd) : '—'}</p>
      </Modal>
    </PageWrapper>
  )
}
