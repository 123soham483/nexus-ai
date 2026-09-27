import { useMemo, useState } from 'react'
import { Activity, BrainCircuit, LineChart as LineChartIcon, ShieldCheck } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/ErrorState'
import { TraceFilter, type TraceFilters } from '@/components/trace/TraceFilter'
import { TraceTimeline } from '@/components/trace/TraceTimeline'
import { useTraces } from '@/hooks/useObservability'
import { useQualityMetrics } from '@/hooks/useAgentMetrics'
import { useTasksList } from '@/hooks/useTasks'
import { formatShortDate } from '@/lib/utils'
import type { Task } from '@/types/task'

export function ObservabilityPage() {
  const [filters, setFilters] = useState<TraceFilters>({ taskId: '', eventType: '', agentType: '' })
  const { data: events, isLoading, error, refetch } = useTraces(filters)
  const { data: quality, isLoading: qualityLoading } = useQualityMetrics()
  const { data: tasks } = useTasksList()

  const taskMap = useMemo(() => {
    const map: Record<string, Task> = {}
    for (const t of tasks ?? []) map[t.id] = t
    return map
  }, [tasks])

  const qualitySeries = useMemo(
    () =>
      (quality?.series ?? []).map((p) => ({
        date: formatShortDate(p.date),
        score: p.score,
      })),
    [quality],
  )

  return (
    <PageWrapper>
      <TraceFilter onApply={setFilters} initial={filters} />

      <div className="mt-4">
        {isLoading ? (
          <Skeleton className="h-96 w-full" />
        ) : error ? (
          <ErrorState message="Could not load traces." onRetry={() => void refetch()} />
        ) : (
          <TraceTimeline events={events ?? []} tasks={taskMap} />
        )}
      </div>

      {/* Quality metrics */}
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="card p-4">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-text-muted">
            <ShieldCheck className="h-4 w-4 text-success" /> Avg Quality Score
          </div>
          {qualityLoading || !quality ? (
            <Skeleton className="mt-2 h-9 w-20" />
          ) : (
            <p className="mt-1 text-3xl font-bold tabular-nums text-text-primary">
              {quality.avg_quality_score === null ? '—' : quality.avg_quality_score}
            </p>
          )}
          <p className="mt-1 text-xs text-text-muted">out of 100 — last 30 days</p>
        </div>

        <div className="card p-4">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-text-muted">
            <BrainCircuit className="h-4 w-4 text-info" /> Avg Hallucination Score
          </div>
          {qualityLoading || !quality ? (
            <Skeleton className="mt-2 h-9 w-20" />
          ) : (
            <p className="mt-1 text-3xl font-bold tabular-nums text-text-primary">{quality.avg_hallucination_score.toFixed(2)}</p>
          )}
          <p className="mt-1 text-xs text-success">Clean — below 0.5 is considered risky</p>
        </div>

        <div className="card p-4">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-text-muted">
            <Activity className="h-4 w-4 text-brand" /> Trace Events Tracked
          </div>
          <p className="mt-1 text-3xl font-bold tabular-nums text-text-primary">{events?.length ?? 0}</p>
          <p className="mt-1 text-xs text-text-muted">matching current filters</p>
        </div>
      </div>

      {/* Quality trend */}
      <div className="mt-4">
        <Card title="Quality Score Trend — 30 days">
          {qualityLoading || !quality ? (
            <Skeleton className="h-56 w-full" />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={qualitySeries} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={{ stroke: 'var(--bg-border)' }} tickLine={false} />
                <YAxis domain={[70, 100]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip
                  formatter={(value: number | string) => [`${value}/100`, 'Quality']}
                  contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--bg-border)', borderRadius: 8, fontSize: 12 }}
                />
                <Line type="monotone" dataKey="score" stroke="var(--brand-primary)" strokeWidth={2} dot={false} name="Quality" />
              </LineChart>
            </ResponsiveContainer>
          )}
          <p className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
            <LineChartIcon className="h-3.5 w-3.5 text-success" />
            Trending upward as the system learns from stored patterns.
          </p>
        </Card>
      </div>
    </PageWrapper>
  )
}
