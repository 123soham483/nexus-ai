/**
 * Mock data store — realistic FAKE values, but the exact SHAPE of the real
 * backend API. Used only when VITE_USE_MOCK !== 'false'.
 */
import type { Task, TaskResult, RoutingDecision } from '@/types/task'
import type { TraceEvent } from '@/types/trace'
import type { CostRecord, CostHistory, BudgetStatus, CostBreakdown } from '@/types/cost'
import type { AgentMetrics } from '@/types/agent'
import type { HITLApproval, HITLHistoryEntry } from '@/types/hitl'
import type { MemoryResult, FailurePattern } from '@/types/memory'
import type { User } from '@/types/auth'
import { uid } from '@/lib/utils'

/* ------------------------------ Helpers ------------------------------- */

function mulberry32(seed: number) {
  return function () {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const rand = mulberry32(1337)
const pick = <T,>(arr: T[]): T => arr[Math.floor(rand() * arr.length)]
const between = (min: number, max: number) => min + rand() * (max - min)
const round2 = (n: number) => Math.round(n * 100) / 100

const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()
const hoursAgo = (h: number) => minsAgo(h * 60)
const daysAgo = (d: number) => minsAgo(d * 24 * 60)

/* ------------------------------ Constants ----------------------------- */

export const MOCK_USER: User = {
  id: 'u_demo_001',
  email: 'demo@nexusai.dev',
  full_name: 'Demo Developer',
  role: 'developer',
  created_at: daysAgo(120),
}

export const AGENT_MODELS: Record<string, string> = {
  planner: 'Claude Sonnet 4.6',
  coder: 'Claude Sonnet 4.6',
  security: 'Claude Sonnet 4.6',
  tester: 'Gemini 1.5 Flash',
  docs: 'Gemini 1.5 Flash',
  reviewer: 'GPT-4o',
  optimizer: 'GPT-4o',
  debugger: 'Claude Sonnet 4.6',
  validator: 'GPT-3.5 Turbo',
}

const GOALS: string[] = [
  'Build a REST API for a todo app with JWT authentication, PostgreSQL database, and comprehensive test coverage',
  'Create a Python script that scrapes product prices from an e-commerce site and emails a daily digest',
  'Refactor the legacy user service to reduce coupling and add typed interfaces',
  'Write a React dashboard with real-time charts for our internal metrics',
  'Set up CI/CD pipeline with GitHub Actions: lint, test, build, and deploy to staging',
  'Design a database schema for multi-tenant SaaS with row-level security',
  'Implement OAuth2 login flow with Google and GitHub providers',
  'Migrate the billing service from Node to Go for lower latency',
  'Add rate limiting and request validation middleware to the API gateway',
  'Build a CLI tool to back up Postgres databases to S3 with encryption',
  'Write end-to-end tests for the checkout flow with Playwright',
  'Containerize the API with Docker and write a docker-compose for local dev',
  'Connect the mobile app to an external OAuth provider and fix token validation',
  'Add a caching layer with Redis to reduce database load by 60%',
  'Generate API documentation from an OpenAPI spec with examples',
  'Implement row-level access control for the analytics service',
  'Build a background job queue with retries and dead-letter handling',
  'Add structured logging and distributed tracing to the payment service',
]

export interface MockState {
  tasks: Task[]
  traces: Record<string, TraceEvent[]>
  scripts: Record<string, TraceEvent[]>
  costRecords: Record<string, CostRecord[]>
  hitl: { pending: HITLApproval[]; history: HITLHistoryEntry[] }
}

export const mockState: MockState = {
  tasks: [],
  traces: {},
  scripts: {},
  costRecords: {},
  hitl: { pending: [], history: [] },
}

/* --------------------------- Task factories --------------------------- */

const TODO_CODE = `from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, auth

app = FastAPI(title="Todo API")

@app.post("/tasks", response_model=schemas.Task)
def create_task(
    payload: schemas.TaskCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    task = models.Task(**payload.model_dump(), owner_id=user.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@app.get("/tasks", response_model=list[schemas.Task])
def list_tasks(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
    limit: int = 50,
):
    return db.query(models.Task).filter(models.Task.owner_id == user.id).limit(limit).all()`

const TODO_TESTS = `import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_task_requires_auth():
    resp = client.post("/tasks", json={"title": "x"})
    assert resp.status_code == 401

def test_full_task_lifecycle():
    token = client.post("/auth/login", json={"email": "a@b.co", "password": "secret1"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/tasks", headers=headers, json={"title": "Ship it"}).json()
    assert created["title"] == "Ship it"
    listed = client.get("/tasks", headers=headers).json()
    assert any(t["id"] == created["id"] for t in listed)
    assert client.delete(f"/tasks/{created['id']}", headers=headers).status_code == 204`

const TODO_DOCS = `# Todo API

A production-grade REST API with JWT auth and Postgres persistence.

## Endpoints

| Method | Path        | Description          |
| ------ | ----------- | -------------------- |
| POST   | /auth/login | Exchange creds for JWT |
| POST   | /tasks      | Create a task        |
| GET    | /tasks      | List my tasks        |
| DELETE | /tasks/{id} | Delete a task        |

## Security

- Passwords hashed with bcrypt
- JWT access tokens (15m) + rotating refresh tokens
- Row-level ownership checks`

interface AgentRunInput {
  agent: string
  startedOffsetSec: number
  durationSec: number
  costUsd: number
  success?: boolean
  parallel?: boolean
}

function buildTraceForTask(
  task: Task,
  opts: {
    confidence?: number
    agents: string[]
    runs: AgentRunInput[]
    estimateUsd: number
    failed?: { at: string; error: string }
    hitl?: { tool: string; resolved?: boolean }
  },
): TraceEvent[] {
  const events: TraceEvent[] = []
  const seq = { n: 0 }
  const base = new Date(task.started_at ?? task.created_at).getTime()
  const at = (offsetSec: number) => new Date(base + offsetSec * 1000).toISOString()
  const ev = (event_type: TraceEvent['event_type'], offsetSec: number, data: Record<string, unknown>, agent_type: string | null = null): TraceEvent => ({
    id: uid(),
    task_id: task.id,
    event_type,
    event_data: data,
    agent_type,
    timestamp: at(offsetSec),
    sequence_number: seq.n++,
  })

  events.push(ev('task_started', 0, {}))
  events.push(ev('failure_patterns_checked', 0.2, { patterns_found: Math.floor(rand() * 3) }))
  events.push(
    ev('routing_complete', 0.5, {
      agents: opts.agents,
      confidence: opts.confidence ?? round2(between(0.86, 0.97)),
    }),
  )
  events.push(ev('cost_estimated', 0.8, { cost_usd: opts.estimateUsd }))

  for (const run of opts.runs) {
    events.push(
      ev('agent_spawned', run.startedOffsetSec, run.parallel ? { group: opts.agents } : {}, run.agent),
    )
    events.push(
      ev('agent_thinking', run.startedOffsetSec + 0.5, { note: 'Analyzing requirements…' }, run.agent),
    )
    events.push(
      ev('agent_tool_called', run.startedOffsetSec + run.durationSec * 0.35, { tool: 'execute_code' }, run.agent),
    )
    events.push(
      ev('agent_tool_result', run.startedOffsetSec + run.durationSec * 0.7, { ok: true }, run.agent),
    )
    events.push(
      ev('agent_completed', run.startedOffsetSec + run.durationSec, {
        cost_usd: run.costUsd,
        duration_seconds: run.durationSec,
        success: run.success ?? true,
      }, run.agent),
    )
  }

  if (opts.hitl) {
    const last = opts.runs[opts.runs.length - 1]
    const atSec = last.startedOffsetSec + last.durationSec + 0.5
    events.push(ev('hitl_required', atSec, { tool: opts.hitl.tool }, 'security'))
    if (opts.hitl.resolved) {
      events.push(ev('hitl_resolved', atSec + 45, { decision: 'approved', by: 'user' }, 'security'))
      events.push(
        ev('agent_completed', atSec + 50, { cost_usd: 1.1, duration_seconds: 50, success: true }, 'security'),
      )
    }
  }

  if (opts.failed) {
    events.push(ev('task_failed', 60, { error: opts.failed.error }))
  } else {
    const lastOffset = opts.hitl?.resolved
      ? 60
      : opts.runs[opts.runs.length - 1].startedOffsetSec + opts.runs[opts.runs.length - 1].durationSec
    const totalDuration = Math.round(lastOffset + 2.5)
    events.push(ev('hallucination_check', lastOffset + 1, { score: round2(between(0.92, 0.99)) }))
    events.push(ev('quality_check', lastOffset + 1.5, { score: task.quality_score ?? 88, passed: true }))
    events.push(ev('learning_stored', lastOffset + 2, { entries: 2 }))
    events.push(ev('task_completed', lastOffset + 2.5, {
      cost_usd: task.actual_cost_usd,
      duration_seconds: totalDuration,
    }))
  }
  return events
}

function buildResult(goal: string, agents: string[]): TaskResult {
  const output: TaskResult['output'] = {}
  for (const a of agents) {
    const meta: TaskResult['output'][string] = {
      agent_type: a,
      success: true,
      output: {},
      confidence_score: round2(between(0.88, 0.98)),
      cost_usd: round2(between(0.2, 6.5)),
      duration_seconds: Math.round(between(6, 60)),
      model_used: AGENT_MODELS[a] ?? 'Claude Sonnet 4.6',
    }
    if (a === 'planner') {
      meta.output.reasoning = `Decomposed the goal into ${agents.length} focused stages. The plan sequences planning → implementation, then fans out verification work in parallel.`
      meta.output.explanation = 'Selected Claude Sonnet for planning/coding, Gemini Flash for cheap parallel verification.'
    } else if (a === 'coder') {
      meta.output.code = TODO_CODE
      meta.output.explanation = 'Implemented the core API with JWT auth, SQLAlchemy models, and per-user scoping.'
      meta.output.reasoning = 'Used FastAPI for speed and automatic OpenAPI generation.'
    } else if (a === 'tester') {
      meta.output.tests = TODO_TESTS
      meta.output.issues = ['Coverage at 87% — add cases for token expiry', 'Add pagination test']
    } else if (a === 'security') {
      meta.output.issues = ['JWT secret rotated to env var', 'Rate limiting added to /auth/login', 'No hardcoded credentials found']
      meta.output.explanation = 'Scanned for OWASP Top 10 issues; all findings remediated automatically.'
    } else if (a === 'docs') {
      meta.output.documentation = TODO_DOCS
    } else if (a === 'validator') {
      meta.output.reasoning = 'Validated output consistency, quality score, and cost efficiency. Approved.'
    } else {
      meta.output.reasoning = 'Completed assigned verification subtask.'
      meta.output.raw = `Agent ${a} completed its stage successfully.`
    }
    output[a] = meta
  }
  return { output, summary: `Completed: ${goal.slice(0, 80)}… Built, tested, and documented.`, files: ['app/main.py', 'app/models.py', 'tests/test_tasks.py', 'README.md'] }
}

function makeRouting(agents: string[]): RoutingDecision {
  const sequential = agents.slice(0, Math.min(2, agents.length))
  const rest = agents.slice(sequential.length)
  const parallel_groups = rest.length ? [rest] : []
  return {
    agents,
    sequential,
    parallel_groups,
    reasoning: 'Sequential planning+implementation, then parallel verification to minimize wall-clock time.',
    confidence: round2(between(0.86, 0.96)),
  }
}

interface NewTaskSpec {
  goal: string
  status: Task['status']
  createdHoursAgo: number
  durationSec?: number
  estimateUsd?: number
  actualUsd?: number
  quality?: number
  agents?: string[]
  failedError?: string
  hitl?: boolean
}

function seedTask(spec: NewTaskSpec): Task {
  const agents = spec.agents ?? ['planner', 'coder', 'security', 'tester', 'docs', 'validator']
  const id = `t_${uid().slice(0, 8)}`
  const created = hoursAgo(spec.createdHoursAgo)
  const started = new Date(new Date(created).getTime() + 4000).toISOString()
  const duration = spec.durationSec ?? Math.round(between(45, 140))
  const estimate = spec.estimateUsd ?? round2(between(8, 22))
  const actual = spec.actualUsd ?? (spec.status === 'completed' ? round2(estimate * between(0.85, 1.02)) : round2(between(0, estimate * 0.5)))

  const task: Task = {
    id,
    goal: spec.goal,
    status: spec.status,
    estimated_cost_usd: estimate,
    actual_cost_usd: actual,
    quality_score: spec.quality ?? (spec.status === 'completed' ? Math.round(between(82, 97)) : null),
    hallucination_score: spec.status === 'completed' ? round2(between(0.86, 1)) : null,
    agents_spawned: spec.status === 'pending' ? [] : agents,
    routing_decision: spec.status === 'pending' ? null : makeRouting(agents),
    result: null,
    created_at: created,
    started_at: spec.status === 'pending' ? null : started,
    completed_at:
      spec.status === 'completed' || spec.status === 'failed' || spec.status === 'cancelled'
        ? new Date(new Date(started).getTime() + duration * 1000).toISOString()
        : null,
    duration_seconds:
      spec.status === 'completed' || spec.status === 'failed' || spec.status === 'cancelled' ? duration : null,
  }

  // Partial result for completed tasks
  if (spec.status === 'completed') {
    task.result = buildResult(spec.goal, agents)
  }

  // Cost records (full for terminal states, partial for running)
  const costRecords: CostRecord[] = []
  let offset = 0
  for (const a of agents) {
    const dur = Math.round(between(5, 40))
    const isRunningTail = (spec.status === 'running' || spec.status === 'hitl_waiting') && offset > agents.length * 0.5
    if (isRunningTail) break
    const costUsd = round2(between(0.2, 6.5))
    costRecords.push({
      id: uid(),
      task_id: id,
      agent_type: a,
      llm_model: AGENT_MODELS[a] ?? 'Claude Sonnet 4.6',
      input_tokens: Math.round(between(400, 9000)),
      output_tokens: Math.round(between(200, 4000)),
      cost_usd: costUsd,
      recorded_at: new Date(new Date(started).getTime() + offset * 1000).toISOString(),
    })
    offset += dur
  }
  mockState.costRecords[id] = costRecords

  // Trace
  const runs: AgentRunInput[] = agents.map((a, i) => ({
    agent: a,
    startedOffsetSec: i === 0 ? 3 : 3 + i * 14 + (i > 1 ? 6 : 0),
    durationSec: Math.round(between(5, 30)),
    costUsd: costRecords[i]?.cost_usd ?? round2(between(0.2, 6.5)),
    parallel: i > 1,
  }))

  const trace = buildTraceForTask(task, {
    agents,
    runs,
    estimateUsd: estimate,
    failed: spec.failedError ? { at: 'coder', error: spec.failedError } : undefined,
    hitl: spec.hitl ? { tool: 'execute_code', resolved: false } : undefined,
  })

  // Running/hitl tasks: keep only the first ~55% of the trace, rest goes into a live script
  if (spec.status === 'running' || spec.status === 'hitl_waiting') {
    const cut = Math.floor(trace.length * (spec.status === 'hitl_waiting' ? 0.65 : 0.45))
    mockState.scripts[id] = trace.slice(cut)
    mockState.traces[id] = trace.slice(0, cut)
    const partialCost = costRecords.reduce((sum, r) => sum + r.cost_usd, 0)
    task.actual_cost_usd = round2(partialCost)
  } else {
    mockState.traces[id] = trace
  }

  mockState.tasks.push(task)
  return task
}

/* ------------------------------ Seeding ------------------------------- */

function seed() {
  const finished = 0
  seedTask({ goal: GOALS[0], status: 'completed', createdHoursAgo: 2, quality: 94 })
  seedTask({ goal: GOALS[1], status: 'completed', createdHoursAgo: 5, quality: 88 })
  seedTask({ goal: GOALS[2], status: 'failed', createdHoursAgo: 7, failedError: 'TypeError: Cannot read properties of undefined (reading \'map\')' })
  seedTask({ goal: GOALS[3], status: 'completed', createdHoursAgo: 9, quality: 91 })
  seedTask({ goal: GOALS[4], status: 'completed', createdHoursAgo: 22, quality: 85 })
  seedTask({ goal: GOALS[5], status: 'completed', createdHoursAgo: 26, quality: 89 })
  seedTask({ goal: GOALS[6], status: 'completed', createdHoursAgo: 30, quality: 93 })
  seedTask({ goal: GOALS[7], status: 'cancelled', createdHoursAgo: 34 })
  seedTask({ goal: GOALS[8], status: 'completed', createdHoursAgo: 49, quality: 87 })
  seedTask({ goal: GOALS[9], status: 'completed', createdHoursAgo: 55, quality: 90 })
  seedTask({ goal: GOALS[10], status: 'completed', createdHoursAgo: 72, quality: 84 })
  seedTask({ goal: GOALS[11], status: 'completed', createdHoursAgo: 96, quality: 92 })
  seedTask({ goal: GOALS[12], status: 'hitl_waiting', createdHoursAgo: 0.2, estimateUsd: 14.6, hitl: true, agents: ['planner', 'coder', 'security'] })
  seedTask({ goal: GOALS[13], status: 'running', createdHoursAgo: 0.1, estimateUsd: 19.2, agents: ['planner', 'coder', 'security', 'tester', 'docs'] })
  seedTask({ goal: GOALS[14], status: 'running', createdHoursAgo: 0.05, estimateUsd: 11.4, agents: ['planner', 'coder', 'tester', 'docs', 'validator'] })
  void finished

  // Budget
  mockBudget = {
    monthly_budget_usd: 60.24, // ≈ ₹5,000
    current_month_spend_usd: 10.2, // ≈ ₹847
    percentage_used: 16.9,
    days_remaining: 19,
  }

  // Cost history
  mockDailyHistory = [
    { period: 'Mon', total_usd: 8.4, task_count: 7, avg_per_task: 1.2 },
    { period: 'Tue', total_usd: 9.2, task_count: 8, avg_per_task: 1.15 },
    { period: 'Wed', total_usd: 7.1, task_count: 6, avg_per_task: 1.18 },
    { period: 'Thu', total_usd: 11.5, task_count: 9, avg_per_task: 1.28 },
    { period: 'Fri', total_usd: 10.2, task_count: 8, avg_per_task: 1.28 },
    { period: 'Sat', total_usd: 8.8, task_count: 6, avg_per_task: 1.47 },
    { period: 'Sun', total_usd: 10.2, task_count: 8, avg_per_task: 1.28 },
  ]
  mockWeeklyHistory = [
    { period: 'Jul 21', total_usd: 52.1, task_count: 41, avg_per_task: 1.27 },
    { period: 'Jul 28', total_usd: 58.4, task_count: 45, avg_per_task: 1.3 },
    { period: 'Aug 4', total_usd: 61.2, task_count: 47, avg_per_task: 1.3 },
  ].reverse()
  // pad to 8 weeks
  const padWeeks = 8 - mockWeeklyHistory.length
  for (let i = 0; i < padWeeks; i++) {
    const d = new Date(Date.now() - (padWeeks - i) * 7 * 24 * 3600 * 1000)
    const label = `${d.toLocaleString('en-US', { month: 'short' })} ${d.getDate()}`
    mockWeeklyHistory.unshift({
      period: label,
      total_usd: round2(44 + rand() * 22),
      task_count: Math.round(34 + rand() * 16),
      avg_per_task: round2(1.1 + rand() * 0.4),
    })
  }
  mockMonthlyHistory = [
    { period: 'Mar', total_usd: 198.4, task_count: 150, avg_per_task: 1.32 },
    { period: 'Apr', total_usd: 221.7, task_count: 164, avg_per_task: 1.35 },
    { period: 'May', total_usd: 245.2, task_count: 178, avg_per_task: 1.38 },
    { period: 'Jun', total_usd: 262.9, task_count: 186, avg_per_task: 1.41 },
    { period: 'Jul', total_usd: 276.1, task_count: 191, avg_per_task: 1.45 },
    { period: 'Aug', total_usd: 10.2, task_count: 8, avg_per_task: 1.28 },
  ]

  // Model breakdown
  mockBreakdown = {
    models: [
      { model: 'Claude Sonnet 4.6', calls: 312, avg_tokens: 4820, total_cost_usd: 7.32, pct: 72 },
      { model: 'Gemini 1.5 Flash', calls: 508, avg_tokens: 2210, total_cost_usd: 1.83, pct: 18 },
      { model: 'GPT-4o', calls: 64, avg_tokens: 3890, total_cost_usd: 0.71, pct: 7 },
      { model: 'GPT-3.5 Turbo', calls: 122, avg_tokens: 1540, total_cost_usd: 0.31, pct: 3 },
    ],
    agents: [
      { agent_type: 'coder', cost_usd: 4.9, pct: 48 },
      { agent_type: 'security', cost_usd: 2.45, pct: 24 },
      { agent_type: 'planner', cost_usd: 1.53, pct: 15 },
      { agent_type: 'tester', cost_usd: 0.71, pct: 7 },
      { agent_type: 'docs', cost_usd: 0.61, pct: 6 },
    ],
    total_usd: 10.2,
  }

  // Agent metrics
  const agents: Array<[string, number, number, number, number, number]> = [
    ['coder', 1247, 96.4, 24.3, 0.063, 89.2],
    ['tester', 1102, 95.1, 31.2, 0.021, 86.4],
    ['security', 883, 92.8, 27.6, 0.042, 84.7],
    ['docs', 764, 97.6, 18.1, 0.014, 91.3],
    ['planner', 721, 98.2, 8.4, 0.035, 93.8],
    ['reviewer', 542, 94.5, 21.9, 0.048, 90.1],
    ['optimizer', 388, 90.7, 35.4, 0.055, 82.6],
    ['debugger', 296, 88.3, 41.2, 0.062, 81.9],
    ['validator', 655, 97.1, 6.8, 0.009, 92.5],
  ]
  mockAgentMetrics = agents.map(([agent_type, total_runs, success_rate, avg_duration_seconds, avg_cost_usd, avg_quality_score]) => ({
    agent_type,
    total_runs,
    success_rate,
    avg_duration_seconds,
    avg_cost_usd: round2(avg_cost_usd),
    avg_quality_score,
    most_common_model: AGENT_MODELS[agent_type] ?? 'Claude Sonnet 4.6',
    last_run_at: hoursAgo(Math.round(between(0.05, 8))),
  }))

  // HITL
  mockState.hitl.pending = [
    {
      approval_id: 'ap_001',
      task_id: mockState.tasks.find((t) => t.status === 'hitl_waiting')!.id,
      tool_name: 'execute_code',
      tool_description: 'This will execute code in a Docker sandbox container',
      tool_params: { language: 'python', code: 'import subprocess\nsubprocess.run(["pip", "install", "requests"])' },
      agent_type: 'security',
      timeout_seconds: 300,
      created_at: minsAgo(2),
      expires_at: minsAgo(-4),
    },
    {
      approval_id: 'ap_002',
      task_id: mockState.tasks.find((t) => t.status === 'running')!.id,
      tool_name: 'write_file',
      tool_description: 'This will overwrite app/config.py with a new configuration',
      tool_params: { path: 'app/config.py', content: 'DEBUG = False\nDATABASE_URL = os.getenv("DATABASE_URL")' },
      agent_type: 'coder',
      timeout_seconds: 300,
      created_at: minsAgo(1),
      expires_at: minsAgo(-5),
    },
  ]
  mockState.hitl.history = [
    { approval_id: 'ap_900', task_id: 't_hist_1', goal: GOALS[0], tool_name: 'execute_code', agent_type: 'security', decision: 'approved', decided_at: hoursAgo(2) },
    { approval_id: 'ap_901', task_id: 't_hist_2', goal: GOALS[6], tool_name: 'write_file', agent_type: 'coder', decision: 'rejected', decided_at: hoursAgo(26) },
    { approval_id: 'ap_902', task_id: 't_hist_3', goal: GOALS[8], tool_name: 'execute_code', agent_type: 'debugger', decision: 'approved', decided_at: hoursAgo(49) },
    { approval_id: 'ap_903', task_id: 't_hist_4', goal: GOALS[10], tool_name: 'browser_use', agent_type: 'tester', decision: 'approved', decided_at: hoursAgo(72) },
  ]

  // Memories
  mockMemories = [
    {
      content: 'Build REST API with JWT auth — used FastAPI + SQLAlchemy; verified pattern works well for CRUD services',
      metadata: { task_id: mockState.tasks[0].id, agent_type: 'coder', quality_score: 94, timestamp: hoursAgo(2) },
      similarity_score: 0.94,
    },
    {
      content: 'Login token validation: prefer pyjwt with leeway=30s and explicit issuer check to avoid clock-skew failures',
      metadata: { task_id: mockState.tasks[6].id, agent_type: 'security', quality_score: 93, timestamp: hoursAgo(30) },
      similarity_score: 0.91,
    },
    {
      content: 'Scraping tasks: add rotating user-agents + backoff; target site blocks default requests UA',
      metadata: { task_id: mockState.tasks[1].id, agent_type: 'coder', quality_score: 88, timestamp: hoursAgo(5) },
      similarity_score: 0.87,
    },
    {
      content: 'CI/CD: cache node_modules + use pnpm; install step dominates runtime otherwise',
      metadata: { task_id: mockState.tasks[4].id, agent_type: 'optimizer', quality_score: 85, timestamp: hoursAgo(22) },
      similarity_score: 0.82,
    },
    {
      content: 'Multi-tenant schema: use tenant_id on every table + RLS policy; avoid connection pooling per tenant',
      metadata: { task_id: mockState.tasks[5].id, agent_type: 'planner', quality_score: 89, timestamp: hoursAgo(26) },
      similarity_score: 0.79,
    },
    {
      content: 'Playwright E2E: run against built bundle, not dev server; flaky by 40% otherwise',
      metadata: { task_id: mockState.tasks[10].id, agent_type: 'tester', quality_score: 84, timestamp: hoursAgo(72) },
      similarity_score: 0.74,
    },
  ]
  mockFailures = [
    { id: 'fp_1', goal: 'Connect the mobile app to an external OAuth provider', failed_agent: 'security', error: 'Token validation failed: signature verification threw because JWKS cache was stale', stored_at: daysAgo(5), similarity_score: 0.9 },
    { id: 'fp_2', goal: 'Migrate billing service from Node to Go', failed_agent: 'coder', error: "TypeError: Cannot read properties of undefined (reading 'map')", stored_at: daysAgo(2), similarity_score: 0.78 },
    { id: 'fp_3', goal: 'Add Redis caching layer', failed_agent: 'tester', error: 'Cache stampede — 5k requests hit origin on cold start', stored_at: daysAgo(8), similarity_score: 0.71 },
    { id: 'fp_4', goal: 'Deploy to staging via GitHub Actions', failed_agent: 'debugger', error: 'Secrets missing in Actions environment for prod workflow', stored_at: daysAgo(12), similarity_score: 0.66 },
  ]

  // Quality series — 30 days trending upward as the system learns
  mockQualitySeries = Array.from({ length: 30 }, (_, i) => ({
    date: daysAgo(29 - i),
    score: Math.round((78 + i * 0.33 + rand() * 2.4) * 10) / 10,
    hallucination: Math.round((1.04 - i * 0.004 - rand() * 0.03) * 100) / 100,
  }))
}

let mockBudget: BudgetStatus = {
  monthly_budget_usd: 60.24,
  current_month_spend_usd: 10.2,
  percentage_used: 16.9,
  days_remaining: 19,
}
let mockDailyHistory: CostHistory[] = []
let mockWeeklyHistory: CostHistory[] = []
let mockMonthlyHistory: CostHistory[] = []
let mockBreakdown: CostBreakdown = { models: [], agents: [], total_usd: 0 }
let mockAgentMetrics: AgentMetrics[] = []
let mockMemories: MemoryResult[] = []
let mockFailures: FailurePattern[] = []
let mockQualitySeries: { date: string; score: number; hallucination: number }[] = []

seed()

/* ---------------------------- Exported data ---------------------------- */

export function getMockBudget(): BudgetStatus {
  return { ...mockBudget }
}
export function setMockBudget(b: Partial<BudgetStatus>): BudgetStatus {
  mockBudget = { ...mockBudget, ...b }
  return { ...mockBudget }
}
export function getMockDailyHistory(): CostHistory[] {
  return mockDailyHistory
}
export function getMockWeeklyHistory(): CostHistory[] {
  return mockWeeklyHistory
}
export function getMockMonthlyHistory(): CostHistory[] {
  return mockMonthlyHistory
}
export function getMockBreakdown(): CostBreakdown {
  return mockBreakdown
}
export function getMockAgentMetrics(): AgentMetrics[] {
  return mockAgentMetrics
}
export function getMockMemories(): MemoryResult[] {
  return mockMemories
}
export function getMockFailures(): FailurePattern[] {
  return mockFailures
}
export function getMockQualitySeries(): { date: string; score: number; hallucination: number }[] {
  return mockQualitySeries
}

/* ------------------------- Live-run generation ------------------------- */
/** Builds a brand-new task + its full live script (for the New Task flow). */
export function generateTaskForGoal(goal: string, context?: Record<string, unknown>): Task {
  const id = `t_${uid().slice(0, 8)}`
  const now = new Date()
  const agents = ['planner', 'coder', 'security', 'tester', 'docs', 'validator']
  // Same formula as costAPI.estimate so the live task matches the preview shown before submit.
  const estimate = round2(0.35 + goal.length * 0.004 + Math.random() * 0.8)
  const task: Task = {
    id,
    goal,
    status: 'routing',
    estimated_cost_usd: estimate,
    actual_cost_usd: 0,
    quality_score: null,
    hallucination_score: null,
    agents_spawned: [],
    routing_decision: null,
    result: null,
    created_at: now.toISOString(),
    started_at: null,
    completed_at: null,
    duration_seconds: null,
  }
  if (context && Object.keys(context).length > 0) {
    void context
  }
  mockState.tasks.unshift(task)
  mockState.traces[id] = []

  // Build a full trace then treat the whole thing as a live script
  const estimateUsd = estimate
  const runs: AgentRunInput[] = agents.map((a, i) => ({
    agent: a,
    startedOffsetSec: i === 0 ? 3 : 3 + i * 12 + (i > 1 ? 5 : 0),
    durationSec: Math.round(between(4, 22)),
    costUsd: round2(between(0.15, 5.4)),
    parallel: i > 1,
  }))
  const full = buildTraceForTask(task, { agents, runs, estimateUsd })
  mockState.scripts[id] = full
  return task
}

/** Applies one live-script event to the mock store (status, cost, result, trace). */
export function applyScriptEvent(taskId: string, event: TraceEvent): void {
  const task = mockState.tasks.find((t) => t.id === taskId)
  if (!task) return
  const seq = event.sequence_number

  // Persist the event into the stored trace so reloads/refetches see the full run.
  mockState.traces[taskId] = [...(mockState.traces[taskId] ?? []), event]
  if (event.event_type === 'task_started' && task.status === 'routing') {
    task.status = 'running'
    task.started_at = event.timestamp
  }
  if (event.event_type === 'routing_complete') {
    task.routing_decision = {
      agents: (event.event_data.agents as string[]) ?? [],
      sequential: [(event.event_data.agents as string[])?.[0] ?? ''].filter(Boolean),
      parallel_groups: [],
      reasoning: 'Auto-routed by the orchestration engine.',
      confidence: (event.event_data.confidence as number) ?? 0.9,
    }
    task.agents_spawned = task.routing_decision.agents
  }
  if (event.event_type === 'agent_spawned') {
    const a = event.agent_type
    if (a && !task.agents_spawned.includes(a)) task.agents_spawned.push(a)
    if (task.routing_decision && !task.routing_decision.agents.includes(a ?? '')) {
      task.routing_decision.agents.push(a ?? '')
    }
  }
  if (event.event_type === 'agent_completed') {
    const cost = event.event_data.cost_usd as number
    if (typeof cost === 'number') task.actual_cost_usd = round2(task.actual_cost_usd + cost)
    if (event.agent_type) {
      const records = mockState.costRecords[taskId] ?? []
      mockState.costRecords[taskId] = [
        ...records,
        {
          id: uid(),
          task_id: taskId,
          agent_type: event.agent_type,
          llm_model: AGENT_MODELS[event.agent_type] ?? 'Claude Sonnet 4.6',
          input_tokens: Math.round(between(400, 9000)),
          output_tokens: Math.round(between(200, 4000)),
          cost_usd: cost,
          recorded_at: event.timestamp,
        },
      ]
    }
  }
  if (event.event_type === 'task_completed') {
    task.status = 'completed'
    task.completed_at = event.timestamp
    task.duration_seconds = (event.event_data.duration_seconds as number) ?? Math.max(1, Math.round((new Date(event.timestamp).getTime() - new Date(task.started_at ?? task.created_at).getTime()) / 1000))
    task.quality_score = Math.round(between(84, 97))
    task.hallucination_score = round2(between(0.92, 0.99))
    task.result = buildResult(task.goal, task.agents_spawned.length ? task.agents_spawned : ['planner', 'coder', 'security', 'tester', 'docs', 'validator'])
  }
  if (event.event_type === 'task_failed') {
    task.status = 'failed'
    task.completed_at = event.timestamp
    task.duration_seconds = task.duration_seconds ?? 60
  }
  void seq
}

/* ------------------------- Mock WebSocket scripts ---------------------- */

/** Events a freshly connected mock socket should emit for a task. */
export function getLiveScript(taskId: string): TraceEvent[] | null {
  const task = mockState.tasks.find((t) => t.id === taskId)
  if (!task) return null
  if (task.status === 'running' || task.status === 'routing') {
    const script = mockState.scripts[taskId]
    if (script && script.length > 0) return script
    return null
  }
  return null
}

/** Cross-task feed used by the dashboard "Live Activity" panel. */
export function buildFeedEvent(): TraceEvent {
  const running = mockState.tasks.filter((t) => t.status === 'running' || t.status === 'routing')
  const pool = running.length ? running : mockState.tasks.filter((t) => t.status === 'hitl_waiting')
  const task = pool.length ? pick(pool) : mockState.tasks[0]
  const agents = task.agents_spawned.length ? task.agents_spawned : ['coder', 'tester', 'security', 'docs']
  const agent = pick(agents)
  const verbs: Array<{ type: TraceEvent['event_type']; text: string }> = [
    { type: 'agent_thinking', text: 'Analyzing requirements…' },
    { type: 'agent_tool_called', text: 'Executing code in sandbox' },
    { type: 'agent_memory_retrieved', text: 'Recalled prior failure pattern' },
    { type: 'agent_completed', text: 'Finished stage' },
  ]
  const v = pick(verbs)
  return {
    id: uid(),
    task_id: task.id,
    event_type: v.type,
    event_data: { note: v.text, tool: 'execute_code' },
    agent_type: agent,
    timestamp: new Date().toISOString(),
    sequence_number: Math.floor(Math.random() * 1000),
  }
}
