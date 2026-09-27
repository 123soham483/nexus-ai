export type TaskStatus =
  | 'pending'
  | 'routing'
  | 'running'
  | 'hitl_waiting'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface Task {
  id: string
  goal: string
  status: TaskStatus
  estimated_cost_usd: number | null
  actual_cost_usd: number
  quality_score: number | null
  hallucination_score: number | null
  agents_spawned: string[]
  routing_decision: RoutingDecision | null
  result: TaskResult | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
}

export interface TaskResult {
  output: Record<string, AgentOutput>
  summary: string
  files?: string[]
}

export interface AgentOutput {
  agent_type: string
  success: boolean
  output: {
    reasoning?: string
    code?: string
    explanation?: string
    issues?: string[]
    tests?: string
    documentation?: string
    raw?: string
  }
  confidence_score: number
  cost_usd: number
  duration_seconds: number
  model_used: string
}

export interface RoutingDecision {
  agents: string[]
  sequential: string[]
  parallel_groups: string[][]
  reasoning: string
  confidence: number
}

export interface TaskCreate {
  goal: string
  context?: Record<string, unknown>
}

export type TaskPriority = 'low' | 'normal' | 'high'
