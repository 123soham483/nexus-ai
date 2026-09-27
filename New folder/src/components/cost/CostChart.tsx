import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatCost } from '@/lib/utils'
import type { CostHistory } from '@/types/cost'

export interface CostChartProps {
  data: CostHistory[]
  /** 0-100 percentage of budget where bars turn amber/red. */
  warnPct?: number
  dangerPct?: number
  height?: number
}

interface TooltipPayload {
  active?: boolean
  payload?: Array<{ payload: CostHistory }>
}

function CostTooltip({ active, payload }: TooltipPayload) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="rounded-lg border border-border bg-elevated px-3 py-2 text-xs shadow-card">
      <p className="font-medium text-text-primary">{d.period}</p>
      <p className="mt-0.5 tabular-nums text-brand-light">{formatCost(d.total_usd)}</p>
      <p className="text-text-muted">
        {d.task_count} tasks · avg {formatCost(d.avg_per_task)}/task
      </p>
    </div>
  )
}

export function CostChart({ data, warnPct = 70, dangerPct = 90, height = 220 }: CostChartProps) {
  const max = Math.max(...data.map((d) => d.total_usd), 1)
  const barColor = (value: number) => {
    const pct = (value / max) * 100
    if (pct >= dangerPct) return 'var(--status-error)'
    if (pct >= warnPct) return 'var(--status-warning)'
    return 'var(--brand-primary)'
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" vertical={false} />
        <XAxis
          dataKey="period"
          tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
          axisLine={{ stroke: 'var(--bg-border)' }}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => formatCost(v)}
        />
        <Tooltip content={<CostTooltip />} cursor={{ fill: 'color-mix(in srgb, var(--brand-primary) 8%, transparent)' }} />
        <Bar dataKey="total_usd" radius={[4, 4, 0, 0]} maxBarSize={42}>
          {data.map((d, i) => (
            <Cell key={i} fill={barColor(d.total_usd)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
