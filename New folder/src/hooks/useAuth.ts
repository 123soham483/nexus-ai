import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { auth } from '@/lib/api'
import { useAuthStore } from '@/store/authStore'
import type { RegisterInput } from '@/types/auth'

export function useAuth() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  const login = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      auth.login(email, password),
    onSuccess: (res) => {
      const { access_token, refresh_token, user: u } = res.data
      useAuthStore.getState().setAuth(u, access_token, refresh_token)
      toast.success('Welcome back to NexusAI')
      navigate('/dashboard', { replace: true })
    },
  })

  const register = useMutation({
    mutationFn: (data: RegisterInput) => auth.register(data),
    onSuccess: (res) => {
      const { access_token, refresh_token, user: u } = res.data
      useAuthStore.getState().setAuth(u, access_token, refresh_token)
      toast.success('Account created — your AI team is ready')
      navigate('/dashboard', { replace: true })
    },
  })

  const logout = async () => {
    try {
      await auth.logout()
    } catch {
      // Even if the server call fails, sign out locally.
    }
    useAuthStore.getState().logout()
    toast('Signed out')
    navigate('/login', { replace: true })
  }

  return { user, isAuthenticated, login, register, logout }
}
