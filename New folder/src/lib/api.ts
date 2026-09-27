import axios from 'axios'
import { useAuthStore } from '@/store/authStore'
import type { User } from '@/types/auth'
import type { Task, TaskCreate, TaskResult, AgentOutput } from '@/types/task'
import type {
  BudgetStatus,
  CostBreakdown,
  CostHistory,
  CostPeriod,
  CostRecord,
} from '@/types/cost'
import type { AgentMetrics } from '@/types/agent'
import type { HITLApproval, HITLHistoryEntry } from '@/types/hitl'
import type { FailurePattern, MemoryResult } from '@/types/memory'
import type { TraceEvent } from '@/types/trace'

/**
 * Real backend client for the NexusAI API (`/api/v1`), JWT auth.
 *
 * The functions below are ADAPTERS: the backend's payloads are mapped onto the
 * exact shapes the UI components consume (the same shapes the mock layer in
 * `mockApi.ts` produces). This keeps every component/store unchanged while
 * making the data real. Where the backend genuinely does not expose something,
 * the adapter says so rather than inventing a value (see `NOT_SUPPORTED`).
 *
 * When VITE_USE_MOCK !== 'false' the exported modules at the bottom are swapped
 * for the in-browser mock so the app still demos without a server.
 */
export const MOCK_MODE = import.meta.env.VITE_USE_MOCK !== 'false'

/** Base URL of the backend, from the environment (never hardcoded). */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

const V1 = '/api/v1'

/** Backend HITL approval timeout, used to derive `expires_at`. */
const HITL_TIMEOUT_SECONDS = Number(import.meta.env.VITE_HITL_TIMEOUT_SECONDS ?? 300)

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

/* ---------------------------- Error helpers ---------------------------- */

/** Marker for an operation the backend does not offer (never faked). */
export class NotSupportedError extends Error {
  readonly code = 'NOT_SUPPORTED'
  constructor(message: string) {
    super(message)
    this.name = 'NotSupportedError'
  }
}

// Request interceptor: attach JWT access token (kept in memory only).
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Response interceptor: on 401, refresh once and replay the original request.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status
    const url: string = error.config?.url ?? ''
    const isAuthCall = url.includes('/auth/login') || url.includes('/auth/refresh')
    if (status === 401 && !error.config?._retried && !isAuthCall) {
      error.config._retried = true
      try {
        const { refreshToken } = useAuthStore.getState()
        if (!refreshToken) throw new Error('no refresh token')
        const res = await axios.post(`${API_BASE_URL}${V1}/auth/refresh`, {
          refresh_token: refreshToken,
        })
        useAuthStore.getState().setAccessToken(res.data.access_token)
        return api(error.config)
      } catch {
        useAuthStore.getState().logout()
        // Let the app's router handle the redirect instead of a hard reload.
        if (window.location.pathname !== '/login') window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

/* ------------------------------ Mappers -------------------------------- */

type Json = Record<string, unknown>

/**
 * The backend serialises datetimes as *naive UTC* (no trailing "Z"), e.g.
 * `2026-09-23T20:35:03.823630`. JavaScript would parse that as **local** time,
 * shifting every relative timestamp and chart bucket by the viewer's UTC offset.
 * Append the zone marker when the API did not supply one.
 */
function utc(value: unknown): string {
  const raw = String(value ?? '')
  if (!raw) return raw
  return /(Z|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : `${raw}Z`
}

/** Trace events as the UI expects them, with UTC timestamps normalised. */
function toTraceEvent(raw: Json): TraceEvent {
  return {
    id: String(raw.id),
    task_id: String(raw.task_id),
    event_type: raw.event_type as TraceEvent['event_type'],
    event_data: (raw.event_data ?? {}) as Record<string, unknown>,
    agent_type: (raw.agent_type as string | null) ?? null,
    timestamp: utc(raw.timestamp),
    sequence_number: Number(raw.sequence_number ?? 0),
  }
}

function toUser(raw: Json): User {
  return {
    id: String(raw.id),
    email: String(raw.email),
    full_name: (raw.full_name as string | null) ?? null,
    // The backend has no role column; derive from superuser + name.
    role: raw.is_superuser ? 'admin' : 'developer',
    created_at: utc(raw.created_at),
  }
}

/**
 * The orchestrator persists `{ summary, outputs: {agent: <raw output>} }`
 * (or `{ error }` on failure). The UI wants richer per-agent records; the
 * extra fields are filled from the task's trace where available.
 */
function toTaskResult(raw: Json | null, trace: TraceEvent[] = []): TaskResult | null {
  if (!raw || typeof raw !== 'object' || Object.keys(raw).length === 0) return null
  if (typeof raw.error === 'string') {
    return { output: {}, summary: raw.error, files: [] }
  }
  const outputs = (raw.outputs ?? {}) as Json
  const output: Record<string, AgentOutput> = {}

  for (const [agent, value] of Object.entries(outputs)) {
    const body = (value && typeof value === 'object' ? value : { raw: String(value) }) as Json
    // Enrich from the last agent_completed trace event for this agent.
    const completed = [...trace]
      .reverse()
      .find((e) => e.event_type === 'agent_completed' && e.agent_type === agent)
    const d = (completed?.event_data ?? {}) as Json
    output[agent] = {
      agent_type: agent,
      success: d.success === undefined ? true : Boolean(d.success),
      // The backend's per-agent output dict is agent-specific; surface it as-is.
      output: body as AgentOutput['output'],
      confidence_score: 0,
      cost_usd: typeof d.cost_usd === 'number' ? d.cost_usd : 0,
      duration_seconds: typeof d.duration_seconds === 'number' ? d.duration_seconds : 0,
      model_used: '',
    }
  }
  return { output, summary: String(raw.summary ?? '') }
}

function toTask(raw: Json): Task {
  const result = raw.result as Json | null
  return {
    id: String(raw.id),
    goal: String(raw.goal),
    status: raw.status as Task['status'],
    estimated_cost_usd: (raw.estimated_cost_usd as number | null) ?? null,
    actual_cost_usd: (raw.actual_cost_usd as number | null) ?? 0,
    quality_score: (raw.quality_score as number | null) ?? null,
    hallucination_score: (raw.hallucination_score as number | null) ?? null,
    agents_spawned: (raw.agents_spawned as string[]) ?? [],
    routing_decision: (raw.routing_decision as Task['routing_decision']) ?? null,
    result: toTaskResult(result),
    created_at: utc(raw.created_at),
    started_at: raw.started_at ? utc(raw.started_at) : null,
    completed_at: raw.completed_at ? utc(raw.completed_at) : null,
    duration_seconds: (raw.duration_seconds as number | null) ?? null,
  }
}

/**
 * Backend cost records carry `agent_run_id` but no agent type. Correlate each
 * record with an `agent_completed` trace event by matching cost value, which is
 * the only shared identifier the API exposes.
 */
function correlateAgentTypes(records: CostRecord[], trace: TraceEvent[]): CostRecord[] {
  const pool: Array<{ agent: string; cost: number; used: boolean }> = []
  for (const e of trace) {
    if (e.event_type !== 'agent_completed' || !e.agent_type) continue
    const cost = e.event_data?.cost_usd
    if (typeof cost === 'number') pool.push({ agent: e.agent_type, cost, used: false })
  }
  return records.map((r) => {
    const hit = pool.find((p) => !p.used && Math.abs(p.cost - r.cost_usd) < 1e-6)
    if (hit) {
      hit.used = true
      return { ...r, agent_type: hit.agent }
    }
    return r
  })
}

function toCostRecord(raw: Json): CostRecord {
  return {
    id: String(raw.id),
    task_id: String(raw.task_id),
    agent_type: '', // filled by correlateAgentTypes when a trace is available
    llm_model: String(raw.llm_model ?? ''),
    input_tokens: Number(raw.input_tokens ?? 0),
    output_tokens: Number(raw.output_tokens ?? 0),
    cost_usd: Number(raw.cost_usd ?? 0),
    recorded_at: utc(raw.recorded_at),
  }
}

/** Aggregate the backend's flat daily history into the period the UI asked for. */
function aggregateHistory(rows: Json[], period: CostPeriod): CostHistory[] {
  const days = rows
    .map((r) => ({
      date: new Date(String(r.date)),
      cost: Number(r.cost_usd ?? 0),
      tasks: Number(r.task_count ?? 0),
    }))
    .sort((a, b) => a.date.getTime() - b.date.getTime())

  const bucket = (d: Date) => {
    if (period === 'daily') {
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    }
    if (period === 'monthly') return `${d.getFullYear()}-${d.getMonth()}`
    const week = new Date(d)
    week.setDate(week.getDate() - week.getDay())
    return `${week.getFullYear()}-${week.getMonth()}-${week.getDate()}`
  }

  const grouped = new Map<string, { date: Date; cost: number; tasks: number }>()
  for (const day of days) {
    const key = bucket(day.date)
    const entry = grouped.get(key) ?? { date: day.date, cost: 0, tasks: 0 }
    entry.cost += day.cost
    entry.tasks += day.tasks
    if (day.date < entry.date) entry.date = day.date
    grouped.set(key, entry)
  }

  const label = (d: Date) => {
    if (period === 'daily') return d.toLocaleString('en-US', { weekday: 'short' })
    if (period === 'monthly') return d.toLocaleString('en-US', { month: 'short' })
    return `${d.toLocaleString('en-US', { month: 'short' })} ${d.getDate()}`
  }

  const window = period === 'daily' ? 7 : period === 'weekly' ? 8 : 6
  return [...grouped.values()]
    .slice(-window)
    .map((v) => ({
      period: label(v.date),
      total_usd: Math.round(v.cost * 100) / 100,
      task_count: v.tasks,
      avg_per_task: v.tasks ? Math.round((v.cost / v.tasks) * 100) / 100 : 0,
    }))
}

function daysRemainingInMonth(): number {
  const now = new Date()
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  return Math.max(1, last.getDate() - now.getDate() + 1)
}

/** Page through `/tasks/` because the backend caps `limit` at 100. */
async function fetchAllTasks(
  params?: { status?: string; offset?: number },
  wanted = 100,
): Promise<Json[]> {
  const out: Json[] = []
  let offset = params?.offset ?? 0
  let guard = 0
  while (out.length < wanted && guard < 10) {
    const page = Math.min(100, wanted - out.length)
    const { data } = await api.get(`${V1}/tasks/`, {
      params: {
        ...(params?.status ? { status: params.status } : {}),
        limit: page,
        offset,
      },
    })
    const batch: Json[] = data.tasks ?? []
    out.push(...batch)
    if (batch.length < page) break
    offset += batch.length
    guard += 1
  }
  return out
}

/** Look up a task id for an approval so approve/reject can build its URL. */
const approvalTaskIds = new Map<string, string>()

/* ------------------------------- Auth --------------------------------- */

/**
 * The backend's login/register return only tokens, so the profile is fetched
 * separately (and the token is installed first, since `/me` is authenticated).
 */
async function establishSession(token: {
  access_token: string
  refresh_token: string
  token_type?: string
}): Promise<{ access_token: string; refresh_token: string; token_type: string; user: User }> {
  const store = useAuthStore.getState()
  store.setAccessToken(token.access_token)
  const me = (await api.get(`${V1}/auth/me`)).data as Json
  const user = toUser(me)
  useAuthStore.getState().setAuth(user, token.access_token, token.refresh_token)
  return {
    access_token: token.access_token,
    refresh_token: token.refresh_token,
    token_type: token.token_type ?? 'bearer',
    user,
  }
}

export const authAPI = {
  register: async (data: { email: string; password: string; full_name?: string }) => {
    const res = await api.post(`${V1}/auth/register`, data)
    return { data: await establishSession(res.data) }
  },
  login: async (email: string, password: string) => {
    // OAuth2 password flow: form-encoded `username` + `password`.
    const form = new URLSearchParams({ username: email, password })
    const res = await api.post(`${V1}/auth/login`, form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    return { data: await establishSession(res.data) }
  },
  logout: async () => {
    const res = await api.post(`${V1}/auth/logout`)
    return { data: res.data }
  },
  me: async () => {
    const res = await api.get(`${V1}/auth/me`)
    return { data: { user: toUser(res.data) } }
  },
}

/* ------------------------------- Tasks -------------------------------- */

export const tasksAPI = {
  create: async (data: TaskCreate) => {
    const res = await api.post(`${V1}/tasks/`, data)
    return { data: toTask(res.data) }
  },
  list: async (params?: { status?: string; limit?: number; offset?: number }) => {
    const rows = await fetchAllTasks(
      { status: params?.status, offset: params?.offset },
      params?.limit ?? 100,
    )
    return { data: rows.map(toTask) }
  },
  get: async (id: string) => {
    const res = await api.get(`${V1}/tasks/${id}`)
    // Enrich the result with per-agent metrics from the trace (best effort).
    let trace: TraceEvent[] = []
    try {
      const t = await api.get(`${V1}/tasks/${id}/trace`)
      trace = ((t.data ?? []) as Json[]).map(toTraceEvent)
    } catch {
      trace = []
    }
    const task = toTask(res.data)
    task.result = toTaskResult((res.data.result as Json) ?? null, trace)
    return { data: task }
  },
  cancel: async (id: string) => {
    const res = await api.delete(`${V1}/tasks/${id}`)
    return { data: res.data }
  },
  trace: async (id: string) => {
    const res = await api.get(`${V1}/tasks/${id}/trace`)
    // Already the UI's shape and ordered oldest → newest; normalise the clock.
    return { data: ((res.data ?? []) as Json[]).map(toTraceEvent) }
  },
  cost: async (id: string) => {
    const [costs, trace] = await Promise.all([
      api.get(`${V1}/tasks/${id}/cost`),
      api
        .get(`${V1}/tasks/${id}/trace`)
        .then((r) => ((r.data ?? []) as Json[]).map(toTraceEvent))
        .catch(() => [] as TraceEvent[]),
    ])
    const records = ((costs.data ?? []) as Json[]).map(toCostRecord)
    return { data: correlateAgentTypes(records, trace) }
  },
}

/* -------------------------------- Cost -------------------------------- */

export const costAPI = {
  estimate: async (goal: string) => {
    const res = await api.post(`${V1}/cost/estimate`, { goal, agent_types: [] })
    const agents: Json[] = res.data.agents ?? []
    const breakdown: Record<string, number> = {}
    for (const a of agents) {
      breakdown[String(a.agent_type)] = Number(a.estimated_cost_usd ?? 0)
    }
    return {
      data: {
        total_usd: Number(res.data.total_estimated_usd ?? 0),
        breakdown,
      },
    }
  },

  history: async (period: CostPeriod) => {
    const res = await api.get(`${V1}/cost/history`)
    return { data: aggregateHistory((res.data ?? []) as Json[], period) }
  },

  breakdown: async (taskId?: string) => {
    if (taskId) {
      const { data: records } = await tasksAPI.cost(taskId)
      const byAgent = new Map<string, number>()
      for (const r of records) {
        const key = r.agent_type || 'unknown'
        byAgent.set(key, (byAgent.get(key) ?? 0) + r.cost_usd)
      }
      const total = [...byAgent.values()].reduce((s, v) => s + v, 0)
      const data: CostBreakdown = {
        models: records.map((r) => ({
          model: r.llm_model,
          calls: 1,
          avg_tokens: r.input_tokens + r.output_tokens,
          total_cost_usd: r.cost_usd,
          pct: total ? Math.round((r.cost_usd / total) * 100) : 0,
        })),
        agents: [...byAgent.entries()]
          .map(([agent_type, cost_usd]) => ({
            agent_type,
            cost_usd,
            pct: total ? Math.round((cost_usd / total) * 100) : 0,
          }))
          .sort((a, b) => b.cost_usd - a.cost_usd),
        total_usd: total,
      }
      return { data }
    }

    // Global breakdown: per-agent spend comes from the real /agents/stats
    // endpoint; the model split is derived from each agent's routed model.
    const [stats, types] = await Promise.all([
      api.get(`${V1}/agents/stats`),
      api.get(`${V1}/agents/`),
    ])
    const modelOf = new Map<string, string>()
    for (const a of (types.data ?? []) as Json[]) {
      modelOf.set(String(a.agent_type), String(a.model ?? ''))
    }
    const agents: Json[] = stats.data.agents ?? []
    const total = agents.reduce((s, a) => s + Number(a.total_cost_usd ?? 0), 0)

    const byModel = new Map<string, { calls: number; cost: number }>()
    for (const a of agents) {
      const model = modelOf.get(String(a.agent_type)) || 'unknown'
      const entry = byModel.get(model) ?? { calls: 0, cost: 0 }
      entry.calls += Number(a.run_count ?? 0)
      entry.cost += Number(a.total_cost_usd ?? 0)
      byModel.set(model, entry)
    }

    const data: CostBreakdown = {
      models: [...byModel.entries()].map(([model, v]) => ({
        model,
        calls: v.calls,
        avg_tokens: 0,
        total_cost_usd: Math.round(v.cost * 1e6) / 1e6,
        pct: total ? Math.round((v.cost / total) * 100) : 0,
      })),
      agents: agents.map((a) => ({
        agent_type: String(a.agent_type),
        cost_usd: Number(a.total_cost_usd ?? 0),
        pct: total ? Math.round((Number(a.total_cost_usd ?? 0) / total) * 100) : 0,
      })),
      total_usd: Math.round(total * 1e6) / 1e6,
    }
    return { data }
  },

  setBudget: async (_monthlyBudget: number) => {
    // The backend exposes GET /cost/budget only — there is no update endpoint,
    // and the tenant budget is owned server-side. Refuse rather than pretend.
    throw new NotSupportedError(
      'Changing the budget is not supported by the API. Update the tenant budget server-side.',
    )
  },

  budget: async () => {
    const res = await api.get(`${V1}/cost/budget`)
    const monthly = Number(res.data.monthly_budget_usd ?? 0)
    const spend = Number(res.data.current_month_spend_usd ?? 0)
    const data: BudgetStatus = {
      monthly_budget_usd: monthly,
      current_month_spend_usd: spend,
      percentage_used: monthly ? Math.round((spend / monthly) * 1000) / 10 : 0,
      days_remaining: daysRemainingInMonth(),
    }
    return { data }
  },
}

/* -------------------------------- HITL -------------------------------- */

/**
 * The HITL API is task-scoped on the backend
 * (`/tasks/{id}/hitl/{pending,history,resolve}`); there is no global queue
 * endpoint, so the queue is assembled from the tenant's hitl_waiting tasks.
 */
function toApproval(raw: Json, taskId: string, goal: string): HITLApproval {
  const createdAt = utc(raw.created_at)
  const createdMs = new Date(createdAt).getTime()
  approvalTaskIds.set(String(raw.id), taskId)
  return {
    approval_id: String(raw.id),
    task_id: taskId,
    // The backend models a HITL request as a human decision with a reason,
    // not a named tool call — surface what actually exists.
    tool_name: 'approval_request',
    tool_description: String(raw.reason ?? ''),
    tool_params: { agent_type: raw.agent_type, goal },
    agent_type: String(raw.agent_type ?? ''),
    timeout_seconds: HITL_TIMEOUT_SECONDS,
    created_at: createdAt,
    expires_at: new Date(createdMs + HITL_TIMEOUT_SECONDS * 1000).toISOString(),
  }
}

async function resolveApprovalTaskId(approvalId: string): Promise<string> {
  const known = approvalTaskIds.get(approvalId)
  if (known) return known
  await hitlAPI.pending() // repopulate the map
  const found = approvalTaskIds.get(approvalId)
  if (!found) {
    throw new Error('That approval is no longer pending.')
  }
  return found
}

export const hitlAPI = {
  pending: async () => {
    const tasks = await fetchAllTasks({ status: 'hitl_waiting' }, 100)
    const results = await Promise.all(
      tasks.map(async (t) => {
        const id = String(t.id)
        try {
          const res = await api.get(`${V1}/tasks/${id}/hitl/pending`)
          return ((res.data ?? []) as Json[]).map((r) => toApproval(r, id, String(t.goal)))
        } catch {
          return [] as HITLApproval[]
        }
      }),
    )
    return { data: results.flat() }
  },

  _decide: async (approvalId: string, approved: boolean) => {
    const taskId = await resolveApprovalTaskId(approvalId)
    const res = await api.post(`${V1}/tasks/${taskId}/hitl/resolve`, {
      request_id: approvalId,
      approved,
      note: null,
    })
    approvalTaskIds.delete(approvalId)
    return { data: res.data }
  },

  approve: async (approvalId: string) => hitlAPI._decide(approvalId, true),
  reject: async (approvalId: string) => hitlAPI._decide(approvalId, false),

  history: async () => {
    const tasks = await fetchAllTasks({}, 50)
    const results = await Promise.all(
      tasks.map(async (t) => {
        const id = String(t.id)
        try {
          const res = await api.get(`${V1}/tasks/${id}/hitl/history`)
          return ((res.data ?? []) as Json[])
            .filter((r) => String(r.status) !== 'pending')
            .map((r) => {
              const entry: HITLHistoryEntry = {
                approval_id: String(r.id),
                task_id: id,
                goal: String(r.goal ?? t.goal),
                tool_name: 'approval_request',
                agent_type: String(r.agent_type ?? ''),
                decision: String(r.status) === 'approved' ? 'approved' : 'rejected',
                decided_at: utc(r.resolved_at ?? r.created_at),
              }
              return entry
            })
        } catch {
          return [] as HITLHistoryEntry[]
        }
      }),
    )
    return {
      data: results
        .flat()
        .sort((a, b) => new Date(b.decided_at).getTime() - new Date(a.decided_at).getTime()),
    }
  },
}

/* --------------------------- Observability ---------------------------- */

export const observabilityAPI = {
  traces: async (params?: { task_id?: string; event_type?: string; agent_type?: string }) => {
    const res = await api.get(`${V1}/observability/traces`, {
      params: {
        task_id: params?.task_id,
        event_type: params?.event_type,
        limit: 500,
      },
    })
    let events = ((res.data ?? []) as Json[]).map(toTraceEvent)
    // Backend returns newest-first; the UI expects oldest-first.
    events = [...events].reverse()
    if (params?.agent_type) {
      events = events.filter((e) => e.agent_type === params.agent_type)
    }
    return { data: events }
  },

  agentMetrics: async () => {
    const [types, stats] = await Promise.all([
      api.get(`${V1}/agents/`),
      api.get(`${V1}/agents/stats`),
    ])
    const registry = ((types.data ?? []) as Json[]).filter((a) => a.implemented !== false)
    const statsByAgent = new Map<string, Json>()
    for (const a of (stats.data.agents ?? []) as Json[]) {
      statsByAgent.set(String(a.agent_type), a)
    }

    // Base the list on the real agent registry (the source of truth for which
    // agents exist), then attach this tenant's measured stats where present.
    // An agent with no runs yet still appears, with zeroed counters.
    const data: AgentMetrics[] = registry
      .map((a) => {
        const agentType = String(a.agent_type)
        const s = statsByAgent.get(agentType)
        const runs = Number(s?.run_count ?? 0)
        return {
          agent_type: agentType,
          total_runs: runs,
          // Backend gives a 0..1 ratio; the UI renders a percentage.
          success_rate: Math.round(Number(s?.success_rate ?? 0) * 1000) / 10,
          avg_duration_seconds: Number(s?.avg_duration_seconds ?? 0),
          avg_cost_usd: runs
            ? Math.round((Number(s?.total_cost_usd ?? 0) / runs) * 1e6) / 1e6
            : 0,
          // Not exposed per agent by the API — rendered as "—", not invented.
          avg_quality_score: null,
          most_common_model: String(a.model ?? ''),
          last_run_at: null,
        }
      })
      .sort((x, y) => y.total_runs - x.total_runs || x.agent_type.localeCompare(y.agent_type))

    return { data }
  },

  qualityMetrics: async () => {
    const [metrics, hallucination, tasks] = await Promise.all([
      api.get(`${V1}/observability/metrics`),
      api.get(`${V1}/observability/hallucination`, { params: { days: 30 } }),
      fetchAllTasks({}, 100).catch(() => [] as Json[]),
    ])

    // Build a real per-day series from the tenant's own tasks.
    const byDay = new Map<string, { score: number[]; halluc: number[] }>()
    for (const t of tasks) {
      const done = t.completed_at ?? t.created_at
      if (!done) continue
      const key = String(done).slice(0, 10)
      const entry = byDay.get(key) ?? { score: [], halluc: [] }
      if (typeof t.quality_score === 'number') entry.score.push(t.quality_score)
      if (typeof t.hallucination_score === 'number') entry.halluc.push(t.hallucination_score)
      byDay.set(key, entry)
    }
    const series = [...byDay.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, v]) => ({
        date,
        score: v.score.length
          ? Math.round((v.score.reduce((s, x) => s + x, 0) / v.score.length) * 10) / 10
          : 0,
        hallucination: v.halluc.length
          ? Math.round((v.halluc.reduce((s, x) => s + x, 0) / v.halluc.length) * 100) / 100
          : 0,
      }))
      .filter((p) => p.score > 0)

    // The API returns null when there is no completed work yet — surface that
    // as "no data" rather than reporting a misleading 0.
    const rawQuality = metrics.data.avg_quality_score
    return {
      data: {
        avg_quality_score:
          rawQuality === null || rawQuality === undefined
            ? null
            : Math.round(Number(rawQuality) * 10) / 10,
        avg_hallucination_score:
          Math.round(Number(hallucination.data.tenant_average ?? 0) * 100) / 100,
        series,
      },
    }
  },
}

/* ------------------------------- Memory ------------------------------- */

function toFailurePattern(raw: Json, index: number): FailurePattern {
  const meta = (raw.metadata ?? {}) as Json
  return {
    id: String(meta.task_id ?? `failure-${index}`),
    goal: String(meta.goal ?? raw.content ?? ''),
    failed_agent: String(meta.failed_agent ?? meta.agent_type ?? ''),
    error: String(meta.error ?? raw.content ?? ''),
    stored_at: meta.timestamp ? utc(meta.timestamp) : '',
    similarity_score:
      typeof raw.similarity_score === 'number' ? raw.similarity_score : undefined,
  }
}

export const memoryAPI = {
  search: async (query: string, n = 5) => {
    const res = await api.post(`${V1}/memory/search`, {
      query,
      collection: 'tasks',
      n_results: n,
    })
    return { data: ((res.data.results ?? []) as MemoryResult[]) }
  },

  failures: async () => {
    // No "list failures" endpoint exists; the failures collection is queried
    // through the real semantic-search endpoint with a broad query.
    const res = await api.post(`${V1}/memory/search`, {
      query: 'failure error failed',
      collection: 'failures',
      n_results: 20,
    })
    return { data: ((res.data.results ?? []) as Json[]).map(toFailurePattern) }
  },

  clear: async () => {
    // No delete endpoint exists on the backend — refuse instead of faking it.
    throw new NotSupportedError(
      'Clearing memory is not supported by the API. Memory can only be removed server-side.',
    )
  },
}

/* ------------------------------- Agents ------------------------------- */

export const agentsAPI = {
  list: async () => observabilityAPI.agentMetrics(),
  stats: async (agentType: string) => {
    const { data } = await observabilityAPI.agentMetrics()
    const match = data.find((a) => a.agent_type === agentType)
    if (!match) throw new Error(`Unknown agent: ${agentType}`)
    return { data: match }
  },
}

export default api

/* ------------------------- Mock-mode swap ------------------------------- */
// Keeps the real axios implementation above while letting the app run
// backend-free during development. Hooks import these module-level names.
import * as mock from './mockApi'

export const auth = MOCK_MODE ? mock.authAPI : authAPI
export const tasks = MOCK_MODE ? mock.tasksAPI : tasksAPI
export const cost = MOCK_MODE ? mock.costAPI : costAPI
export const hitl = MOCK_MODE ? mock.hitlAPI : hitlAPI
export const observability = MOCK_MODE ? mock.observabilityAPI : observabilityAPI
export const memory = MOCK_MODE ? mock.memoryAPI : memoryAPI
export const agents = MOCK_MODE ? mock.agentsAPI : agentsAPI
