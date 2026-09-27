import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ChevronDown, ChevronRight, Rocket } from 'lucide-react'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Button } from '@/components/ui/Button'
import { TaskGoalInput } from '@/components/task/TaskGoalInput'
import { TaskCostPreview } from '@/components/task/TaskCostPreview'
import { cn, formatCost, parseJSONSafe } from '@/lib/utils'
import { useCreateTask } from '@/hooks/useTasks'
import { useCostEstimate, useBudget } from '@/hooks/useCost'
import { apiErrorMessage } from '@/lib/utils'

const PRIORITIES = [
  { value: 'low', label: 'Low' },
  { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' },
] as const

export function NewTaskPage() {
  const navigate = useNavigate()
  const [goal, setGoal] = useState('')
  const [debouncedGoal, setDebouncedGoal] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [contextText, setContextText] = useState('')
  const [priority, setPriority] = useState<'low' | 'normal' | 'high'>('normal')
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Debounce goal by 1s before requesting a cost estimate.
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedGoal(goal), 1000)
    return () => window.clearTimeout(t)
  }, [goal])

  const canEstimate = debouncedGoal.trim().length >= 10
  const { data: estimate, isFetching: estimating } = useCostEstimate(debouncedGoal, canEstimate)
  const { data: budget } = useBudget()
  const createTask = useCreateTask()

  const context = parseJSONSafe(contextText)
  const remaining = budget ? Math.max(0, budget.monthly_budget_usd - budget.current_month_spend_usd) : null
  const overBudget = estimate && remaining != null ? estimate.total_usd > remaining : false
  const canSubmit = goal.trim().length >= 10 && !overBudget

  const submit = () => {
    setSubmitError(null)
    createTask.mutate(
      { goal: goal.trim(), context: context ?? undefined },
      {
        onSuccess: (res) => {
          navigate(`/tasks/${res.data.id}`)
        },
        onError: (err) => setSubmitError(apiErrorMessage(err)),
      },
    )
  }

  return (
    <PageWrapper maxWidth="max-w-2xl">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-text-primary">Run a new task</h2>
        <p className="mt-1 text-sm text-text-secondary">
          Describe what you want to build or solve. NexusAI routes it to the right agents.
        </p>
      </div>

      {/* Step 1 — goal */}
      <TaskGoalInput value={goal} onChange={setGoal} />

      {/* Step 2 — cost estimate */}
      <div className="mt-4">
        <TaskCostPreview
          estimate={estimate}
          loading={estimating}
          budget={budget}
          goalLength={goal.trim().length}
        />
      </div>

      {overBudget && estimate && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-error/30 bg-error/10 px-3 py-2.5 text-sm text-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Estimated cost {formatCost(estimate.total_usd)} exceeds your remaining budget of {remaining != null ? formatCost(remaining) : '—'}.
        </div>
      )}

      {/* Step 3 — advanced options */}
      <div className="mt-4">
        <button
          onClick={() => setShowAdvanced((s) => !s)}
          className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface px-4 py-3 text-sm font-medium text-text-secondary transition-colors hover:border-border/80 hover:text-text-primary"
        >
          {showAdvanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Advanced Options
        </button>
        {showAdvanced && (
          <div className="mt-3 animate-fade-in space-y-4">
            <div>
              <label className="label">Context (JSON)</label>
              <textarea
                value={contextText}
                onChange={(e) => setContextText(e.target.value)}
                rows={4}
                placeholder='{"language": "python", "framework": "fastapi", "extra_notes": "…"}'
                className="input resize-y font-mono text-xs"
              />
              {contextText && !context && (
                <p className="mt-1.5 text-xs text-warning">Invalid JSON — context will be ignored.</p>
              )}
            </div>
            <div>
              <label className="label">Priority</label>
              <div className="flex gap-2">
                {PRIORITIES.map((p) => (
                  <button
                    key={p.value}
                    onClick={() => setPriority(p.value)}
                    className={cn(
                      'rounded-lg border px-4 py-2 text-sm font-medium transition-colors',
                      priority === p.value
                        ? 'border-brand bg-brand/15 text-brand-light'
                        : 'border-border text-text-secondary hover:border-border/80',
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {submitError && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-error/30 bg-error/10 px-3 py-2.5 text-sm text-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {submitError}
        </div>
      )}

      {/* Submit */}
      <div className="mt-6">
        <Button
          size="lg"
          fullWidth
          disabled={!canSubmit}
          loading={createTask.isPending}
          onClick={submit}
          className="btn-gold-live h-12 bg-gradient-to-r from-brand to-brand-light text-base"
        >
          {createTask.isPending ? 'Starting agents…' : (
            <>
              Run Task <Rocket className="h-4 w-4" />
            </>
          )}
        </Button>
        <p className="mt-2 text-center text-xs text-text-muted">
          {goal.trim().length < 10
            ? 'Write at least 10 characters to enable submission.'
            : 'You will be redirected to the live task view as soon as it starts.'}
        </p>
      </div>
    </PageWrapper>
  )
}
