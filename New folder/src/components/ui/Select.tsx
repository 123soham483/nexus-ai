import { forwardRef, type SelectHTMLAttributes, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode
  options: Array<{ value: string; label: string }>
  placeholder?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, options, placeholder, className, id, ...props }, ref) => {
    const selectId = id ?? props.name
    return (
      <div className="w-full">
        {label && (
          <label htmlFor={selectId} className="label">
            {label}
          </label>
        )}
        <div className="relative">
          <select ref={ref} id={selectId} className={cn('input appearance-none pr-8', className)} {...props}>
            {placeholder && <option value="">{placeholder}</option>}
            {options.map((o) => (
              <option key={o.value} value={o.value} className="bg-elevated text-text-primary">
                {o.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
        </div>
      </div>
    )
  },
)
Select.displayName = 'Select'
