/**
 * In-browser mock API — same request/response shapes as the real backend,
 * used while VITE_USE_MOCK !== 'false' so the app demos without a server.
 */
import {
  MOCK_USER,
  mockState,
  generateTaskForGoal,
  getMockBudget,
  setMockBudget,
  getMockDailyHistory,
  getMockWeeklyHistory,
  getMockMonthlyHistory,
  getMockBreakdown,
  getMockAgentMetrics,
  getMockMemories,
  getMockFailures,
  getMockQualitySeries,
} from '@/lib/mockData'
import { dispatchMockEvent } from '@/lib/mockWs'
import { uid } from '@/lib/utils'
import type { TaskCreate } from '@/types/task'
import type { TraceEvent, TraceEventType } from '@/types/trace'
import type { CostPeriod } from '@/types/cost'
import type { User } from '@/types/auth'

const delay = (ms = 250 + Math.random() * 350) => new Promise((r) => setTimeout(r, ms))
const res = <T,>(data: T, ms?: number) => delay(ms).then(() => ({ data }))

function fail(status: number, message: string): Promise<never> {
  return Promise.reject({
    response: { status, data: { detail: message } },
    isMock: true,
  })
}

/* --------------------------------- Auth -------------------------------- */

export const authAPI = {
  register: async (data: { email: string; password: string; full_name?: string }) => {
    await delay(600)
    const user: User = {
      id: `u_${uid().slice(0, 8)}`,
      email: data.email,
      full_name: data.full_name || data.email.split('@')[0] || 'Developer',
      role: 'developer',
      created_at: new Date().toISOString(),
    }
    return res({
      access_token: `mock-at-${uid()}`,
      refresh_token: `mock-rt-${uid()}`,
      token_type: 'bearer',
      user,
    })
  },
  login: async (email: string, password: string) => {
    await delay(550)
    if (!email || !password) return fail(401, 'Wrong email or password')
    return res({
      access_token: `mock-at-${uid()}`,
      refresh_token: `mock-rt-${uid()}`,
      token_type: 'bearer',
      user: { ...MOCK_USER, email },
    })
  },
  logout: () => res({ ok: true }),
  me: () => res({ user: MOCK_USER }),
}

/* -------------------------------- Tasks -------------------------------- */

export const tasksAPI = {
  create: async (data: TaskCreate) => {
    await delay(400)
    const task = generateTaskForGoal(data.goal, data.context)
    return res(task)
  },
  list: async (params?: { status?: string; limit?: number; offset?: number }) => {
    await delay()
    let list = [...mockState.tasks].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )
    if (params?.status) {
      list = list.filter((t) => t.status === params.status)
    }
    const offset = params?.offset ?? 0
    const limit = params?.limit ?? 500
    return res(list.slice(offset, offset + limit))
  },
  get: async (id: string) => {
    await delay()
    const task = mockState.tasks.find((t) => t.id === id)
    if (!task) return fail(404, 'Task not found')
    return res(task)
  },
  cancel: async (id: string) => {
    await delay()
    const task = mockState.tasks.find((t) => t.id === id)
    if (!task) return fail(404, 'Task not found')
    task.status = 'cancelled'
    task.completed_at = new Date().toISOString()
    task.duration_seconds = task.duration_seconds ?? 0
    return res(task)
  },
  trace: async (id: string) => {
    await delay()
    return res(mockState.traces[id] ?? [])
  },
  cost: async (id: string) => {
    await delay()
    return res(mockState.costRecords[id] ?? [])
  },
}

/* --------------------------------- Cost -------------------------------- */

const ESTIMATE_WEIGHTS: Record<string, number> = {
  planner: 0.17,
  coder: 0.5,
  security: 0.2,
  tester: 0.06,
  docs: 0.03,
  validator: 0.02,
  reviewer: 0.01,
  optimizer: 0.01,
}

export const costAPI = {
  estimate: async (goal: string) => {
    await delay(500)
    const total = Math.round((0.35 + goal.length * 0.004 + Math.random() * 0.8) * 100) / 100
    const breakdown: Record<string, number> = {}
    for (const [agent, w] of Object.entries(ESTIMATE_WEIGHTS)) {
      breakdown[agent] = Math.round(total * w * 100) / 100
    }
    return res({ total_usd: total, breakdown })
  },
  history: async (period: CostPeriod) => {
    await delay()
    const data =
      period === 'daily'
        ? getMockDailyHistory()
        : period === 'weekly'
          ? getMockWeeklyHistory()
          : getMockMonthlyHistory()
    return res(data)
  },
  breakdown: async (taskId?: string) => {
    await delay()
    if (taskId) {
      const records = mockState.costRecords[taskId] ?? []
      const byAgent = new Map<string, { cost: number }>()
      for (const r of records) {
        byAgent.set(r.agent_type, { cost: (byAgent.get(r.agent_type)?.cost ?? 0) + r.cost_usd })
      }
      const total = [...byAgent.values()].reduce((s, v) => s + v.cost, 0)
      return res({
        models: records.map((r) => ({
          model: r.llm_model,
          calls: 1,
          avg_tokens: r.input_tokens + r.output_tokens,
          total_cost_usd: r.cost_usd,
          pct: total ? Math.round((r.cost_usd / total) * 100) : 0,
        })),
        agents: [...byAgent.entries()].map(([agent_type, v]) => ({
          agent_type,
          cost_usd: v.cost,
          pct: total ? Math.round((v.cost / total) * 100) : 0,
        })),
        total_usd: total,
      })
    }
    return res(getMockBreakdown())
  },
  setBudget: async (monthlyBudget: number) => {
    await delay()
    const b = setMockBudget({ monthly_budget_usd: monthlyBudget })
    return res(b)
  },
  budget: async () => {
    await delay()
    return res(getMockBudget())
  },
}

/* --------------------------------- HITL -------------------------------- */

function emitHITLFollowup(taskId: string, decision: 'approved' | 'rejected'): void {
  const task = mockState.tasks.find((t) => t.id === taskId)
  if (!task) return
  const now = Date.now()
  let seq = 900
  const mk = (event_type: TraceEventType, offsetMs: number, data: Record<string, unknown>, agent_type: string | null): TraceEvent => ({
    id: uid(),
    task_id: taskId,
    event_type,
    event_data: data,
    agent_type,
    timestamp: new Date(now + offsetMs).toISOString(),
    sequence_number: seq++,
  })
  window.setTimeout(
    () => dispatchMockEvent(taskId, mk('hitl_resolved', 0, { decision, by: 'user' }, 'security')),
    300,
  )
  if (decision === 'approved') {
    window.setTimeout(
      () =>
        dispatchMockEvent(
          taskId,
          mk('agent_completed', 2500, { cost_usd: 1.1, duration_seconds: 45, success: true }, 'security'),
        ),
      2800,
    )
    window.setTimeout(
      () => dispatchMockEvent(taskId, mk('quality_check', 3200, { score: 90, passed: true }, null)),
      3800,
    )
    window.setTimeout(
      () =>
        dispatchMockEvent(taskId, mk('task_completed', 3500, { cost_usd: 14.2, duration_seconds: 68 }, null)),
      4100,
    )
  } else {
    window.setTimeout(
      () =>
        dispatchMockEvent(
          taskId,
          mk('task_failed', 1200, { error: 'Approval rejected by user' }, null),
        ),
      1500,
    )
  }
}

export const hitlAPI = {
  pending: async () => {
    await delay()
    return res([...mockState.hitl.pending])
  },
  approve: async (approvalId: string) => {
    await delay(400)
    const idx = mockState.hitl.pending.findIndex((a) => a.approval_id === approvalId)
    if (idx === -1) return fail(404, 'Approval no longer pending')
    const [approval] = mockState.hitl.pending.splice(idx, 1)
    const goal = mockState.tasks.find((t) => t.id === approval.task_id)?.goal ?? ''
    mockState.hitl.history.unshift({
      approval_id: approvalId,
      task_id: approval.task_id,
      goal,
      tool_name: approval.tool_name,
      agent_type: approval.agent_type,
      decision: 'approved',
      decided_at: new Date().toISOString(),
    })
    emitHITLFollowup(approval.task_id, 'approved')
    return res({ ok: true })
  },
  reject: async (approvalId: string) => {
    await delay(400)
    const idx = mockState.hitl.pending.findIndex((a) => a.approval_id === approvalId)
    if (idx === -1) return fail(404, 'Approval no longer pending')
    const [approval] = mockState.hitl.pending.splice(idx, 1)
    const goal = mockState.tasks.find((t) => t.id === approval.task_id)?.goal ?? ''
    mockState.hitl.history.unshift({
      approval_id: approvalId,
      task_id: approval.task_id,
      goal,
      tool_name: approval.tool_name,
      agent_type: approval.agent_type,
      decision: 'rejected',
      decided_at: new Date().toISOString(),
    })
    emitHITLFollowup(approval.task_id, 'rejected')
    return res({ ok: true })
  },
  history: async () => {
    await delay()
    return res(mockState.hitl.history)
  },
}

/* --------------------------- Observability ----------------------------- */

export const observabilityAPI = {
  traces: async (params?: { task_id?: string; event_type?: string; agent_type?: string }) => {
    await delay()
    let all: TraceEvent[] = []
    for (const [taskId, events] of Object.entries(mockState.traces)) {
      all = all.concat(events)
      void taskId
    }
    all.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    if (params?.task_id) all = all.filter((e) => e.task_id === params.task_id)
    if (params?.event_type) all = all.filter((e) => e.event_type === params.event_type)
    if (params?.agent_type) all = all.filter((e) => e.agent_type === params.agent_type)
    return res(all.slice(-2000))
  },
  agentMetrics: async () => {
    await delay()
    return res(getMockAgentMetrics())
  },
  qualityMetrics: async () => {
    await delay()
    const series = getMockQualitySeries()
    const avg = series.reduce((s, p) => s + p.score, 0) / series.length
    const hall = series.reduce((s, p) => s + p.hallucination, 0) / series.length
    return res({
      avg_quality_score: Math.round(avg * 10) / 10,
      avg_hallucination_score: Math.round(hall * 100) / 100,
      series,
    })
  },
}

/* -------------------------------- Memory ------------------------------- */

function similarity(query: string, content: string): number {
  const q = new Set(query.toLowerCase().split(/\W+/).filter((w) => w.length > 2))
  const c = content.toLowerCase()
  let hits = 0
  for (const w of q) if (c.includes(w)) hits++
  const base = q.size === 0 ? 0.4 : hits / Math.max(1, q.size)
  return Math.min(0.99, Math.max(0.3, base * 0.75 + 0.35 + Math.random() * 0.08))
}

export const memoryAPI = {
  search: async (query: string, n = 5) => {
    await delay(650)
    const results = getMockMemories()
      .map((m) => ({ ...m, similarity_score: similarity(query, m.content) }))
      .sort((a, b) => b.similarity_score - a.similarity_score)
      .slice(0, n)
    return res(results)
  },
  failures: async () => {
    await delay()
    return res(getMockFailures())
  },
  clear: async () => {
    await delay(400)
    return res({ ok: true })
  },
}

/* -------------------------------- Agents ------------------------------- */

export const agentsAPI = {
  list: async () => {
    await delay()
    return res(getMockAgentMetrics())
  },
  stats: async (agentType: string) => {
    await delay()
    const m = getMockAgentMetrics().find((a) => a.agent_type === agentType)
    if (!m) return fail(404, 'Agent not found')
    return res(m)
  },
}

