import { cn } from '@/lib/utils'

export interface TaskGoalInputProps {
  value: string
  onChange: (value: string) => void
  maxLength?: number
  minLength?: number
  className?: string
}

export function TaskGoalInput({ value, onChange, maxLength = 2000, minLength = 10, className }: TaskGoalInputProps) {
  const over = value.length > maxLength
  const ok = value.length >= minLength

  return (
    <div className={className}>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={maxLength}
        rows={5}
        placeholder="Describe what you want to build or solve…
Example: Build a REST API for a todo app with JWT authentication, PostgreSQL database, and comprehensive test coverage."
        className="input resize-y py-3 font-mono text-sm leading-relaxed"
      />
      <div className="mt-1.5 flex items-center justify-between text-xs">
        <span className="text-text-muted">
          Be specific. Include: language, framework, requirements.
          {!ok && value.length > 0 && <span className="ml-2 text-warning">Minimum {minLength} characters.</span>}
        </span>
        <span className={cn('tabular-nums', over ? 'text-error' : ok ? 'text-success' : 'text-text-muted')}>
          {value.length} / {maxLength}
        </span>
      </div>
    </div>
  )
}
