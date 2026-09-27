export interface CostRecord {
  id: string
  task_id: string
  agent_type: string
  llm_model: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
  recorded_at: string
}

export interface CostHistory {
  period: string
  total_usd: number
  task_count: number
  avg_per_task: number
}

export interface CostEstimate {
  total_usd: number
  breakdown: Record<string, number>
}

export interface BudgetStatus {
  monthly_budget_usd: number
  current_month_spend_usd: number
  percentage_used: number
  days_remaining: number
}

export interface ModelCost {
  model: string
  calls: number
  avg_tokens: number
  total_cost_usd: number
  pct: number
}

export interface AgentCost {
  agent_type: string
  cost_usd: number
  pct: number
}

export interface CostBreakdown {
  models: ModelCost[]
  agents: AgentCost[]
  total_usd: number
}

export type CostPeriod = 'daily' | 'weekly' | 'monthly'
