import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { ProtectedLayout } from '@/components/layout/ProtectedLayout'
import { LoginPage } from '@/pages/auth/LoginPage'
import { RegisterPage } from '@/pages/auth/RegisterPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { NewTaskPage } from '@/pages/NewTaskPage'
import { TasksPage } from '@/pages/TasksPage'
import { TaskDetailPage } from '@/pages/TaskDetailPage'
import { CostPage } from '@/pages/CostPage'
import { AgentsPage } from '@/pages/AgentsPage'
import { ObservabilityPage } from '@/pages/ObservabilityPage'
import { MemoryPage } from '@/pages/MemoryPage'
import { HITLPage } from '@/pages/HITLPage'
import { SettingsPage } from '@/pages/SettingsPage'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          {/* Protected */}
          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/tasks/new" element={<NewTaskPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
            <Route path="/cost" element={<CostPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/observability" element={<ObservabilityPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/hitl" element={<HITLPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>

          {/* Redirects */}
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
