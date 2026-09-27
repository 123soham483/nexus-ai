export interface AgentMetrics {
  agent_type: string
  total_runs: number
  success_rate: number
  avg_duration_seconds: number
  avg_cost_usd: number
  /** Null when the API does not expose per-agent quality (rendered as "—"). */
  avg_quality_score: number | null
  most_common_model: string
  /** Null when the API does not expose the last run time (rendered as "—"). */
  last_run_at: string | null
}

export type AgentRunStatus = 'waiting' | 'running' | 'done' | 'failed'
