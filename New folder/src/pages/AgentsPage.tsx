import { useMemo } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/ErrorState'
import { AgentCard } from '@/components/agent/AgentCard'
import { getAgentMeta, formatDuration, formatPercent } from '@/lib/utils'
import { useAgentMetrics } from '@/hooks/useAgentMetrics'

export function AgentsPage() {
  const { data: metrics, isLoading, error, refetch } = useAgentMetrics()

  const successData = useMemo(
    () =>
      [...(metrics ?? [])]
        .sort((a, b) => a.success_rate - b.success_rate)
        .map((m) => ({ name: getAgentMeta(m.agent_type).short, value: m.success_rate })),
    [metrics],
  )

  const durationData = useMemo(
    () =>
      [...(metrics ?? [])]
        .sort((a, b) => a.avg_duration_seconds - b.avg_duration_seconds)
        .map((m) => ({ name: getAgentMeta(m.agent_type).short, value: m.avg_duration_seconds })),
    [metrics],
  )

  const successColor = (v: number) => (v >= 90 ? 'var(--status-success)' : v >= 70 ? 'var(--status-warning)' : 'var(--status-error)')

  if (isLoading) {
    return (
      <PageWrapper>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <Skeleton key={i} className="h-52 w-full" />
          ))}
        </div>
      </PageWrapper>
    )
  }

  if (error || !metrics) {
    return (
      <PageWrapper>
        <ErrorState message="Could not load agent metrics." onRetry={() => void refetch()} />
      </PageWrapper>
    )
  }

  return (
    <PageWrapper>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {metrics.map((m) => (
          <AgentCard key={m.agent_type} metrics={m} />
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Success Rate by Agent">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={successData} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 8 }}>
              <XAxis type="number" domain={[0, 100]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
              <YAxis type="category" dataKey="name" width={72} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                formatter={(value: number | string) => formatPercent(Number(value))}
                cursor={{ fill: 'color-mix(in srgb, var(--brand-primary) 8%, transparent)' }}
                contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--bg-border)', borderRadius: 8, fontSize: 12 }}
              />
              <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={16}>
                {successData.map((d) => (
                  <Cell key={d.name} fill={successColor(d.value)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Average Duration by Agent">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={durationData} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 8 }}>
              <XAxis type="number" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}s`} />
              <YAxis type="category" dataKey="name" width={72} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                formatter={(value: number | string) => formatDuration(Number(value))}
                cursor={{ fill: 'color-mix(in srgb, var(--brand-primary) 8%, transparent)' }}
                contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--bg-border)', borderRadius: 8, fontSize: 12 }}
              />
              <Bar dataKey="value" fill="var(--brand-primary)" radius={[0, 4, 4, 0]} maxBarSize={16} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </PageWrapper>
  )
}
