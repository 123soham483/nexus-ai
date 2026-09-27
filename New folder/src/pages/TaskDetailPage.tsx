import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Clock, Rocket, ShieldAlert, XCircle } from 'lucide-react'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/ErrorState'
import { Modal } from '@/components/ui/Modal'
import { Badge } from '@/components/ui/Badge'
import { AgentStatusDot } from '@/components/agent/AgentStatusDot'
import { AgentActivityFeed } from '@/components/agent/AgentActivityFeed'
import { AgentTimeline } from '@/components/agent/AgentTimeline'
import { TaskStatusBadge } from '@/components/task/TaskStatusBadge'
import { TaskResultPanel } from '@/components/task/TaskResultPanel'
import { CostBreakdown } from '@/components/cost/CostBreakdown'
import { CostMeter } from '@/components/cost/CostMeter'
import { HITLBanner } from '@/components/hitl/HITLBanner'
import { CopyButton } from '@/components/ui/CopyButton'
import { apiErrorMessage, formatCost, formatDuration, formatFullDate, getAgentMeta, idShort, truncate } from '@/lib/utils'
import type { TraceEvent } from '@/types/trace'
import { useTask, useCancelTask } from '@/hooks/useTasks'
import { useTaskTrace, useTaskCostRecords } from '@/hooks/useTaskTrace'
import { useTaskWebSocket } from '@/hooks/useWebSocket'
import { usePendingApprovals, useApproveApproval, useRejectApproval } from '@/hooks/useHITL'
import { useTaskStore } from '@/store/taskStore'

function useElapsed(task: { started_at: string | null; status: string } | undefined) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!task || (task.status !== 'running' && task.status !== 'routing' && task.status !== 'hitl_waiting')) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [task])
  if (!task?.started_at) return null
  return Math.floor((now - new Date(task.started_at).getTime()) / 1000)
}

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: task, isLoading, error, refetch } = useTask(id)
  const { data: trace, isLoading: traceLoading } = useTaskTrace(id)
  const { data: costRecords } = useTaskCostRecords(id)
  const liveEvents = useTaskStore((s) => s.liveEvents)
  const liveCost = useTaskStore((s) => s.liveCost)
  const liveAgentStatuses = useTaskStore((s) => s.liveAgentStatuses)
  const { data: approvals } = usePendingApprovals()
  const approve = useApproveApproval()
  const reject = useRejectApproval()
  const cancelTask = useCancelTask()
  const [confirmCancel, setConfirmCancel] = useState(false)

  useTaskWebSocket(id)

  const running = task?.status === 'running' || task?.status === 'routing'
  const elapsed = useElapsed(task)

  const approval = useMemo(
    () => approvals?.find((a) => a.task_id === id),
    [approvals, id],
  )

  // Merge API trace + live WS events, dedupe by id, sort by sequence.
  const events = useMemo(() => {
    const map = new Map<string, TraceEvent>()
    for (const e of trace ?? []) map.set(e.id, e)
    for (const e of liveEvents) map.set(e.id, e)
    return [...map.values()].sort((a, b) => a.sequence_number - b.sequence_number)
  }, [trace, liveEvents])

  if (isLoading) {
    return (
      <PageWrapper>
        <div className="space-y-4">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-40 w-full" />
          <div className="grid gap-4 lg:grid-cols-5">
            <Skeleton className="h-80 lg:col-span-3" />
            <Skeleton className="h-80 lg:col-span-2" />
          </div>
        </div>
      </PageWrapper>
    )
  }

  if (error || !task) {
    return (
      <PageWrapper>
        <ErrorState message={error ? apiErrorMessage(error) : 'Task not found'} onRetry={() => void refetch()} />
      </PageWrapper>
    )
  }

  const modelSummary = task.agents_spawned.length
    ? [...new Set(task.agents_spawned.map((a) => getAgentMeta(a).model))].join(' + ')
    : null
  const displayCost = liveCost > 0 ? liveCost : task.actual_cost_usd

  return (
    <PageWrapper maxWidth="max-w-7xl">
      <button
        onClick={() => navigate(-1)}
        className="mb-4 flex items-center gap-1.5 text-sm text-text-muted transition-colors hover:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" /> Back
      </button>

      <div className="grid gap-4 lg:grid-cols-5">
        {/* LEFT COLUMN */}
        <div className="space-y-4 lg:col-span-3">
          {/* Panel A — header */}
          <Card padded={false}>
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <TaskStatusBadge status={task.status} />
                {running && (
                  <span className="flex items-center gap-1.5 text-xs text-brand-light">
                    <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-brand" />
                    {elapsed != null ? `elapsed ${formatDuration(elapsed)}` : 'starting…'}
                  </span>
                )}
              </div>
              {running && (
                <Button variant="danger" size="sm" onClick={() => setConfirmCancel(true)}>
                  <XCircle className="h-3.5 w-3.5" /> Cancel Task
                </Button>
              )}
            </div>
            <div className="p-4">
              <h2 className="text-base font-semibold leading-relaxed text-text-primary">{task.goal}</h2>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                {task.agents_spawned.length > 0 && (
                  <Badge tone="brand" dot>
                    {task.agents_spawned.length} agents
                  </Badge>
                )}
                {modelSummary && <span className="text-text-muted">{modelSummary}</span>}
                {task.routing_decision && (
                  <span className="text-text-muted">· routing confidence {Math.round(task.routing_decision.confidence * 100)}%</span>
                )}
                <span className="ml-auto font-mono text-[11px] text-text-muted">{idShort(task.id)}</span>
              </div>
            </div>
          </Card>

          {/* Panel B — live activity feed (signature) */}
          <Card
            title={
              <span className="flex items-center gap-2">
                Agent Activity
                {running && <AgentStatusDot status="running" pulse />}
              </span>
            }
            action={running && <span className="flex items-center gap-2 text-xs text-text-secondary"><CostMeter value={displayCost} /></span>}
          >
            {traceLoading ? (
              <Skeleton className="h-[320px] w-full" />
            ) : (
              <div className="-m-4">
                <AgentActivityFeed
                  events={events}
                  running={running}
                  maxHeight={400}
                  className="rounded-none border-0"
                  emptyText="Waiting for the first trace event…"
                />
              </div>
            )}
          </Card>

          {/* Panel C — agent timeline */}
          <Card title="Execution Timeline">
            <AgentTimeline
              routing={task.routing_decision}
              statuses={liveAgentStatuses}
              events={events}
              taskStatus={task.status}
            />
          </Card>

          {/* Panel D — HITL approval */}
          {approval && task.status === 'hitl_waiting' && (
            <HITLBanner
              approval={approval}
              approving={approve.isPending}
              rejecting={reject.isPending}
              onApprove={() => approve.mutate(approval.approval_id)}
              onReject={() => reject.mutate(approval.approval_id)}
            />
          )}
        </div>

        {/* RIGHT COLUMN */}
        <div className="space-y-4 lg:col-span-2">
          {/* Panel E — result */}
          {task.status === 'completed' && task.result && (
            <TaskResultPanel result={task.result} />
          )}
          {task.status === 'failed' && (
            <Card>
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-error/10 text-error">
                  <ShieldAlert className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-error">Task failed</p>
                  <p className="mt-1 text-xs text-text-secondary">
                    The agents could not complete this task. Check the activity feed for the failure point, or retry with a more specific goal.
                  </p>
                  <Button variant="secondary" size="sm" className="mt-3" onClick={() => navigate('/tasks/new')}>
                    <Rocket className="h-3.5 w-3.5" /> Retry with a new task
                  </Button>
                </div>
              </div>
            </Card>
          )}

          {/* Panel F — cost breakdown */}
          <Card title="Cost Breakdown">
            <CostBreakdown records={costRecords} estimatedUsd={task.estimated_cost_usd} loading={!costRecords} />
          </Card>

          {/* Panel G — task info */}
          <Card title="Task Info">
            <dl className="space-y-2.5 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-text-muted">Task ID</dt>
                <dd className="flex items-center gap-1 font-mono text-xs text-text-secondary">
                  {idShort(task.id)}
                  <CopyButton text={task.id} />
                </dd>
              </div>
              <InfoRow label="Created" value={formatFullDate(task.created_at)} />
              <InfoRow label="Started" value={task.started_at ? formatFullDate(task.started_at) : '—'} />
              <InfoRow label="Completed" value={task.completed_at ? formatFullDate(task.completed_at) : running ? 'In progress' : '—'} />
              <InfoRow
                label="Duration"
                value={task.duration_seconds != null ? formatDuration(task.duration_seconds) : running && elapsed != null ? formatDuration(elapsed) : '—'}
              />
              {task.quality_score != null && <InfoRow label="Quality score" value={`${task.quality_score} / 100`} />}
              {task.hallucination_score != null && (
                <InfoRow label="Hallucination" value={`${task.hallucination_score.toFixed(2)} (${task.hallucination_score >= 0.9 ? 'Clean' : 'Watch'})`} />
              )}
              <div className="flex items-center justify-between gap-3 border-t border-border pt-2.5">
                <dt className="flex items-center gap-1.5 text-text-muted">
                  <Clock className="h-3.5 w-3.5" /> Estimated cost
                </dt>
                <dd className="tabular-nums text-text-secondary">{formatCost(task.estimated_cost_usd)}</dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>

      <Modal
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        title="Cancel this task?"
        description="Agents stop immediately. Work and costs already incurred are kept."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmCancel(false)}>
              Keep running
            </Button>
            <Button
              variant="danger"
              loading={cancelTask.isPending}
              onClick={() =>
                cancelTask.mutate(task.id, {
                  onSuccess: () => setConfirmCancel(false),
                })
              }
            >
              Cancel task
            </Button>
          </>
        }
      >
        <p className="text-sm text-text-secondary">“{truncate(task.goal, 120)}”</p>
      </Modal>
    </PageWrapper>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-text-muted">{label}</dt>
      <dd className="text-right text-text-secondary">{value}</dd>
    </div>
  )
}
