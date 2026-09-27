import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode
  error?: string | null
  hint?: ReactNode
  leftIcon?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, leftIcon, className, id, ...props }, ref) => {
    const inputId = id ?? props.name
    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="label">
            {label}
          </label>
        )}
        <div className="relative">
          {leftIcon && (
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted">
              {leftIcon}
            </span>
          )}
          <input
            ref={ref}
            id={inputId}
            className={cn('input', leftIcon && 'pl-9', error && 'border-error focus:border-error focus:ring-error', className)}
            {...props}
          />
        </div>
        {error && <p className="mt-1.5 text-xs text-error">{error}</p>}
        {!error && hint && <p className="mt-1.5 text-xs text-text-muted">{hint}</p>}
      </div>
    )
  },
)
Input.displayName = 'Input'
