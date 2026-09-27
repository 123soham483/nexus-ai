import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { AlertTriangle, Eye, EyeOff, Lock, Mail } from 'lucide-react'
import { AuthShell } from '@/pages/auth/AuthShell'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { useAuth } from '@/hooks/useAuth'
import { apiErrorMessage } from '@/lib/utils'
import { MOCK_MODE } from '@/lib/api'

export function LoginPage() {
  const { isAuthenticated, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (isAuthenticated) return <Navigate to="/dashboard" replace />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    login.mutate(
      { email, password },
      {
        onError: (err) => {
          const msg = apiErrorMessage(err)
          setError(msg.toLowerCase().includes('password') || msg.toLowerCase().includes('email') || msg.toLowerCase().includes('credential')
            ? 'Wrong email or password'
            : 'Something went wrong. Try again.')
        },
      },
    )
  }

  return (
    <AuthShell>
      <h2 className="text-2xl font-bold text-text-primary">Sign in</h2>
      <p className="mt-1 text-sm text-text-secondary">Welcome back to NexusAI</p>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-error/30 bg-error/10 px-3 py-2.5 text-sm text-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <form onSubmit={submit} className="mt-6 space-y-4">
        <Input
          name="email"
          type="email"
          label="Email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          leftIcon={<Mail className="h-4 w-4" />}
          autoFocus
          required
        />
        <div className="relative">
          <Input
            name="password"
            type={showPassword ? 'text' : 'password'}
            label="Password"
            placeholder="••••••••"
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

        <Button type="submit" fullWidth size="lg" loading={login.isPending}>
          Sign in
        </Button>
      </form>

      <p className="mt-5 text-center text-sm text-text-secondary">
        Don&apos;t have an account?{' '}
        <Link to="/register" className="font-medium text-brand-light hover:underline">
          Register
        </Link>
      </p>

      {MOCK_MODE && (
        <div className="mt-6 rounded-lg border border-border bg-elevated/40 px-3 py-2 text-center text-xs text-text-muted">
          Demo mode — any email and password work. Try{' '}
          <code className="text-brand-light">demo@nexusai.dev</code>
        </div>
      )}
    </AuthShell>
  )
}
