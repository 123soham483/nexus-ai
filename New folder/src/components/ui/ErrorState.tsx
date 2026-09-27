import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/Button'

export interface ErrorStateProps {
  message?: string
  onRetry?: () => void
  compact?: boolean
}

export function ErrorState({ message = 'Something went wrong. Try again.', onRetry, compact }: ErrorStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center text-center ${compact ? 'px-4 py-6' : 'px-6 py-12'}`}>
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-error/30 bg-error/10 text-error">
        <AlertTriangle className="h-5 w-5" />
      </div>
      <p className="text-sm text-text-secondary">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" /> Retry
        </Button>
      )}
    </div>
  )
}
