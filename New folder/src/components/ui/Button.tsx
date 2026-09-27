import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success' | 'outline'
type Size = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  fullWidth?: boolean
}

const VARIANTS: Record<Variant, string> = {
  primary:
    'btn-gold-shine bg-brand text-[#06281c] hover:bg-brand-light shadow-[0_0_20px_var(--brand-glow)] focus-visible:ring-brand',
  secondary: 'bg-elevated text-text-primary hover:bg-border border border-border',
  ghost: 'text-text-secondary hover:bg-elevated hover:text-text-primary',
  danger: 'bg-error/10 text-error border border-error/30 hover:bg-error/20',
  success: 'bg-success/10 text-success border border-success/30 hover:bg-success/20',
  outline: 'border border-border text-text-primary hover:border-brand hover:text-brand-light',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-9 px-4 text-sm',
  lg: 'h-11 px-5 text-sm',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', loading, fullWidth, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn('btn', VARIANTS[variant], SIZES[size], fullWidth && 'w-full', className)}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  ),
)
Button.displayName = 'Button'
