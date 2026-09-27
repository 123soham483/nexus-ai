import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { AlertTriangle, Eye, EyeOff, Lock, Mail, User } from 'lucide-react'
import { AuthShell } from '@/pages/auth/AuthShell'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { PasswordStrengthMeter } from '@/components/ui/PasswordStrengthMeter'
import { useAuth } from '@/hooks/useAuth'
import { apiErrorMessage } from '@/lib/utils'

export function RegisterPage() {
  const { isAuthenticated, register } = useAuth()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (isAuthenticated) return <Navigate to="/dashboard" replace />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    register.mutate(
      { email, password, full_name: fullName || undefined },
      {
        onError: (err) => setError(apiErrorMessage(err)),
      },
    )
  }

  return (
    <AuthShell>
      <h2 className="text-2xl font-bold text-text-primary">Create account</h2>
      <p className="mt-1 text-sm text-text-secondary">Assemble your AI team in under a minute</p>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-error/30 bg-error/10 px-3 py-2.5 text-sm text-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <form onSubmit={submit} className="mt-6 space-y-4">
        <Input
          name="full_name"
          label="Full name (optional)"
          placeholder="Ada Lovelace"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          leftIcon={<User className="h-4 w-4" />}
        />
        <Input
          name="email"
          type="email"
          label="Email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          leftIcon={<Mail className="h-4 w-4" />}
          required
        />
        <div className="relative">
          <Input
            name="password"
            type={showPassword ? 'text' : 'password'}
            label="Password"
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            leftIcon={<Lock className="h-4 w-4" />}
            required
          />
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            className="absolute right-3 top-[34px] text-text-muted transition-colors hover:text-text-primary"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        <PasswordStrengthMeter password={password} />
        <Input
          name="confirm"
          type={showPassword ? 'text' : 'password'}
          label="Confirm password"
          placeholder="Repeat your password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          leftIcon={<Lock className="h-4 w-4" />}
          required
        />

        <Button type="submit" fullWidth size="lg" loading={register.isPending}>
          Create account
        </Button>
      </form>

      <p className="mt-5 text-center text-sm text-text-secondary">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-brand-light hover:underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  )
}
