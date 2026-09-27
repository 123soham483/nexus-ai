import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, ChevronLeft, ChevronRight, ListTodo, Plus, XCircle } from 'lucide-react'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { Modal } from '@/components/ui/Modal'
import { AgentAvatar } from '@/components/agent/AgentAvatar'
import { TaskStatusBadge } from '@/components/task/TaskStatusBadge'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { cn, formatCost, formatDuration, formatRelative, truncate } from '@/lib/utils'
import { useTasksList, useCancelTask } from '@/hooks/useTasks'
import type { Task, TaskStatus } from '@/types/task'

const PAGE_SIZE = 20
type Filter = 'all' | TaskStatus

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'completed', label: 'Completed' },
  { key: 'failed', label: 'Failed' },
]

export function TasksPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('all')
  const [page, setPage] = useState(0)
  const [cancelTarget, setCancelTarget] = useState<Task | null>(null)
  const { data: tasks, isLoading } = useTasksList()
  const cancelTask = useCancelTask()

  const filtered = useMemo(() => {
    const list = filter === 'all' ? (tasks ?? []) : (tasks ?? []).filter((t) => t.status === filter)
    return list
  }, [tasks, filter])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const rows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)

  return (
    <PageWrapper>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => {
            const count = f.key === 'all' ? (tasks?.length ?? 0) : (tasks ?? []).filter((t) => t.status === f.key).length
            return (
              <button
                key={f.key}
                onClick={() => {
                  setFilter(f.key)
                  setPage(0)
                }}
                className={cn(
                  'rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors',
                  filter === f.key
                    ? 'border-brand bg-brand/15 text-brand-light'
                    : 'border-border text-text-secondary hover:border-border/80 hover:text-text-primary',
                )}
              >
                {f.label}
                <span className="ml-1.5 tabular-nums opacity-70">{count}</span>
              </button>
            )
          })}
        </div>
        <Link to="/tasks/new">
          <Button size="sm">
            <Plus className="h-3.5 w-3.5" /> New Task
          </Button>
        </Link>
      </div>

      <div className="mt-4">
        <Card padded={false}>
          {isLoading || !tasks ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<ListTodo className="h-6 w-6" />}
              title={filter === 'all' ? 'No tasks yet' : `No ${filter} tasks`}
              description={filter === 'all' ? 'Run your first task and watch the agents work.' : 'Try a different filter.'}
              action={
                filter === 'all' ? (
                  <Link to="/tasks/new">
                    <Button>
                      Run your first task <ArrowRight className="h-4 w-4" />
                    </Button>
                  </Link>
                ) : undefined
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[840px] text-sm">
                <thead>
                  <tr className="border-b border-border bg-elevated/40 text-left text-[11px] uppercase tracking-wide text-text-muted">
                    <th className="px-4 py-2.5 font-medium">Goal</th>
                    <th className="px-3 py-2.5 font-medium">Status</th>
                    <th className="hidden px-3 py-2.5 font-medium lg:table-cell">Agents</th>
                    <th className="hidden px-3 py-2.5 font-medium md:table-cell">Quality</th>
                    <th className="px-3 py-2.5 text-right font-medium">Cost</th>
                    <th className="hidden px-3 py-2.5 font-medium sm:table-cell">Duration</th>
                    <th className="hidden px-3 py-2.5 font-medium md:table-cell">Created</th>
                    <th className="px-3 py-2.5 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((task) => {
                    const running = task.status === 'running' || task.status === 'routing'
                    return (
                      <tr
                        key={task.id}
                        onClick={() => navigate(`/tasks/${task.id}`)}
                        className={cn(
                          'group cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-elevated/40',
                          running && 'border-l-2 border-l-brand',
                          task.status === 'failed' && 'border-l-2 border-l-error',
                          task.status === 'completed' && 'border-l-2 border-l-success',
                        )}
                      >
                        <td className="max-w-[260px] px-4 py-3">
                          <p className="truncate font-medium text-text-primary group-hover:text-brand-light">
                            {truncate(task.goal, 60)}
                          </p>
                          <p className="font-mono text-[11px] text-text-muted">{task.id}</p>
                        </td>
                        <td className="px-3 py-3">
                          <TaskStatusBadge status={task.status} />
                        </td>
                        <td className="hidden px-3 py-3 lg:table-cell">
                          {task.agents_spawned.length > 0 ? (
                            <div className="flex">
                              {task.agents_spawned.slice(0, 5).map((a) => (
                                <AgentAvatar key={a} agentType={a} size="sm" className="-ml-1.5 first:ml-0 ring-2 ring-surface" />
                              ))}
                              {task.agents_spawned.length > 5 && (
                                <span className="-ml-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-elevated text-[10px] font-medium text-text-secondary ring-2 ring-surface">
                                  +{task.agents_spawned.length - 5}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-text-muted">—</span>
                          )}
                        </td>
                        <td className="hidden px-3 py-3 md:table-cell">
                          {task.quality_score != null ? (
                            <div className="flex w-24 items-center gap-2">
                              <ProgressBar value={task.quality_score} warnAt={70} dangerAt={90} className="w-14" />
                              <span className="text-xs tabular-nums text-text-secondary">{task.quality_score}</span>
                            </div>
                          ) : (
                            <span className="text-xs text-text-muted">—</span>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums text-text-primary">{formatCost(task.actual_cost_usd)}</td>
                        <td className="hidden px-3 py-3 tabular-nums text-text-secondary sm:table-cell">
                          {task.duration_seconds != null ? formatDuration(task.duration_seconds) : '—'}
                        </td>
                        <td className="hidden px-3 py-3 text-xs text-text-muted md:table-cell">{formatRelative(task.created_at)}</td>
                        <td className="px-3 py-3">
                          <div className="flex items-center justify-end gap-1">
                            {(task.status === 'running' || task.status === 'routing' || task.status === 'hitl_waiting' || task.status === 'pending') && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setCancelTarget(task)
                                }}
                                className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-error/10 hover:text-error"
                                aria-label="Cancel task"
                              >
                                <XCircle className="h-4 w-4" />
                              </button>
                            )}
                            <ArrowRight className="h-4 w-4 text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-brand-light" />
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {filtered.length > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-border px-4 py-3">
              <p className="text-xs text-text-muted">
                {safePage * PAGE_SIZE + 1}–{Math.min(filtered.length, (safePage + 1) * PAGE_SIZE)} of {filtered.length}
              </p>
              <div className="flex gap-1.5">
                <Button variant="secondary" size="sm" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
                  <ChevronLeft className="h-4 w-4" /> Prev
                </Button>
                <Button variant="secondary" size="sm" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}>
                  Next <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>

      <Modal
        open={cancelTarget !== null}
        onClose={() => setCancelTarget(null)}
        title="Cancel this task?"
        description="The agents will stop immediately. Partial work and costs already incurred are kept."
        footer={
          <>
            <Button variant="ghost" onClick={() => setCancelTarget(null)}>
              Keep running
            </Button>
            <Button
              variant="danger"
              loading={cancelTask.isPending}
              onClick={() => {
                if (cancelTarget) {
                  cancelTask.mutate(cancelTarget.id, {
                    onSuccess: () => setCancelTarget(null),
                  })
                }
              }}
            >
              Cancel task
            </Button>
          </>
        }
      >
        {cancelTarget && (
          <p className="text-sm text-text-secondary">
            “{truncate(cancelTarget.goal, 120)}”
          </p>
        )}
      </Modal>
    </PageWrapper>
  )
}
