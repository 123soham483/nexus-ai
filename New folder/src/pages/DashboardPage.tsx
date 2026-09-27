import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Activity, ArrowRight, Bot, CheckCircle2, Plus, TrendingDown, TrendingUp, Wallet } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { AgentStatusDot } from '@/components/agent/AgentStatusDot'
import { AgentActivityFeed } from '@/components/agent/AgentActivityFeed'
import { TaskCard } from '@/components/task/TaskCard'
import { CostChart } from '@/components/cost/CostChart'
import { formatCost, formatPercent, getAgentMeta } from '@/lib/utils'
import { useTasksList } from '@/hooks/useTasks'
import { useCostHistory, useBudget } from '@/hooks/useCost'
import { useLiveActivity } from '@/hooks/useLiveActivity'

function StatCard({
  icon,
  label,
  value,
  sub,
  trend,
  trendUp,
  trendGood = true,
  valueRight,
}: {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  trend?: string
  trendUp?: boolean
  trendGood?: boolean
  valueRight?: React.ReactNode
}) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-text-muted">{label}</p>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-elevated text-brand-light">
          {icon}
        </span>
      </div>
      <div className="mt-2 flex items-end justify-between gap-2">
        <div className="text-2xl font-bold tabular-nums text-text-primary">{value}</div>
        {valueRight}
      </div>
      {sub && <p className="mt-1 text-xs text-text-secondary">{sub}</p>}
      {trend && (
        <p className={`mt-2 inline-flex items-center gap-1 text-xs font-medium ${trendGood ? 'text-success' : 'text-error'}`}>
          {trendUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
          {trend}
        </p>
      )}
    </div>
  )
}

function SuccessDonut({ pct }: { pct: number }) {
  return (
    <div className="relative h-12 w-12">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={[{ v: pct }, { v: 100 - pct }]} dataKey="v" innerRadius={15} outerRadius={22} startAngle={90} endAngle={-270} stroke="var(--bg-surface)" isAnimationActive={false}>
            <Cell fill="var(--status-success)" />
            <Cell fill="var(--bg-border)" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

export function DashboardPage() {
  const { data: tasks, isLoading: tasksLoading } = useTasksList()
  const { data: dailyHistory, isLoading: historyLoading } = useCostHistory('daily')
  const { data: budget } = useBudget()
  const liveEvents = useLiveActivity(20)

  const stats = useMemo(() => {
    if (!tasks) return null
    const today = tasks.filter((t) => new Date(t.created_at).toDateString() === new Date().toDateString())
    const running = tasks.filter((t) => t.status === 'running' || t.status === 'routing')
    const completed = tasks.filter((t) => t.status === 'completed')
    const failed = tasks.filter((t) => t.status === 'failed')
    const successRate = completed.length + failed.length > 0 ? (completed.length / (completed.length + failed.length)) * 100 : 100
    const activeAgents = [...new Set(running.flatMap((t) => t.agents_spawned))].slice(0, 3)
    return { todayCount: today.length, runningCount: running.length, completedCount: completed.length, successRate, activeAgents, running }
  }, [tasks])

  const todaySpend = dailyHistory?.[dailyHistory.length - 1]

  const goalFor = useMemo(() => {
    const map = new Map((tasks ?? []).map((t) => [t.id, t.goal]))
    return (taskId: string) => map.get(taskId)
  }, [tasks])

  return (
    <PageWrapper>
      {/* Section A — stats row */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={<CheckCircle2 className="h-4 w-4" />}
          label="Tasks Today"
          value={stats ? stats.todayCount : <Skeleton className="h-7 w-14" />}
          sub={stats ? `${stats.runningCount} running, ${stats.completedCount} completed` : undefined}
          trend="↑ 20% vs yesterday"
          trendUp
        />
        <StatCard
          icon={<Activity className="h-4 w-4" />}
          label="Success Rate"
          value={stats ? formatPercent(stats.successRate, 1) : <Skeleton className="h-7 w-14" />}
          valueRight={stats ? <SuccessDonut pct={stats.successRate} /> : undefined}
          sub="Last 30 days"
          trend="↑ 2.1% vs last week"
          trendUp
        />
        <StatCard
          icon={<Wallet className="h-4 w-4" />}
          label="Today's Spend"
          value={historyLoading ? <Skeleton className="h-7 w-14" /> : todaySpend ? formatCost(todaySpend.total_usd) : '—'}
          sub={todaySpend ? `Avg ${formatCost(todaySpend.avg_per_task)} per task` : undefined}
          trend="↓ 8% vs yesterday"
        />
        <StatCard
          icon={<Bot className="h-4 w-4" />}
          label="Active Agents"
          value={stats ? stats.runningCount : <Skeleton className="h-7 w-14" />}
          sub={
            stats && stats.activeAgents.length > 0 ? (
              <span className="flex items-center gap-2">
                {stats.activeAgents.map((a) => (
                  <span key={a} className="flex items-center gap-1">
                    <AgentStatusDot status="running" agentType={a} pulse />
                    {getAgentMeta(a).short}
                  </span>
                ))}
              </span>
            ) : (
              'No agents running'
            )
          }
        />
      </div>

      {/* Sections B + D — live feed and weekly chart */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card
          title={
            <span className="flex items-center gap-2">
              Live Activity
              {stats && stats.runningCount > 0 && <span className="h-2 w-2 animate-pulse-dot rounded-full bg-success" />}
            </span>
          }
        >
          <div className="-m-4">
            <AgentActivityFeed
              events={liveEvents}
              running={stats ? stats.runningCount > 0 : false}
              maxHeight={320}
              goalFor={goalFor}
              emptyText="No active tasks. Run a task and watch your agents work in real time."
              className="rounded-none border-0"
            />
          </div>
        </Card>

        <Card title="Spending This Week" action={budget ? <span className="text-xs text-text-muted">{formatPercent(budget.percentage_used, 1)} of budget used</span> : undefined}>
          {historyLoading || !dailyHistory ? (
            <Skeleton className="h-[220px] w-full" />
          ) : (
            <CostChart data={dailyHistory} />
          )}
        </Card>
      </div>

      {/* Section C — recent tasks */}
      <div className="mt-4">
        <Card
          title="Recent Tasks"
          action={
            <Link to="/tasks/new">
              <Button size="sm">
                <Plus className="h-3.5 w-3.5" /> New Task
              </Button>
            </Link>
          }
        >
          {tasksLoading || !tasks ? (
            <div className="space-y-2">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : tasks.length === 0 ? (
            <EmptyState
              icon={<Bot className="h-6 w-6" />}
              title="No tasks yet"
              description="Run your first task and watch the agents work."
              action={
                <Link to="/tasks/new">
                  <Button>
                    Create your first task <ArrowRight className="h-4 w-4" />
                  </Button>
                </Link>
              }
            />
          ) : (
            <div className="space-y-2">
              {tasks.slice(0, 8).map((task) => (
                <TaskCard key={task.id} task={task} />
              ))}
            </div>
          )}
        </Card>
      </div>
    </PageWrapper>
  )
}
