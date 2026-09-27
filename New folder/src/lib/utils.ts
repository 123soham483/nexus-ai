import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { format, formatDistanceToNow } from 'date-fns'
import {
  Calendar,
  Code,
  FlaskConical,
  Shield,
  FileText,
  Eye,
  Zap,
  Bug,
  CheckCircle2,
  Bell,
  CircleDashed,
  Wrench,
  AlignLeft,
  Search,
  ScanSearch,
  Wallet,
  UserCheck,
  Circle,
  CheckCircle,
  XCircle,
  Loader2,
  type LucideIcon,
} from 'lucide-react'
import type { TaskStatus } from '@/types/task'
import { useSettingsStore } from '@/store/settingsStore'

/** Merge Tailwind classes, resolving conflicts. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/* ------------------------------ Currency ------------------------------ */

export type Currency = 'INR' | 'USD' | 'EUR'

export const CURRENCY_META: Record<Currency, { symbol: string; rate: number; label: string }> = {
  INR: { symbol: '₹', rate: 83, label: 'Indian Rupee (₹)' },
  USD: { symbol: '$', rate: 1, label: 'US Dollar ($)' },
  EUR: { symbol: '€', rate: 0.92, label: 'Euro (€)' },
}

/**
 * Format a USD cost value into the user's selected display currency.
 * API values are USD (cost_usd); display currency defaults to INR per the design.
 */
export function formatCost(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  const currency = useSettingsStore.getState().currency
  const { symbol, rate } = CURRENCY_META[currency]
  const converted = value * rate
  const formatted = converted.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return `${symbol}${formatted}`
}

export function formatCostCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  const currency = useSettingsStore.getState().currency
  const { symbol, rate } = CURRENCY_META[currency]
  const converted = value * rate
  if (converted >= 1000) {
    return `${symbol}${(converted / 1000).toLocaleString('en-IN', { maximumFractionDigits: 1 })}k`
  }
  return `${symbol}${converted.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

/* ----------------------------- Numbers -------------------------------- */

export function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toLocaleString('en-IN')
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value.toFixed(digits)}%`
}

export function formatTokens(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  if (value >= 1000) return `${(value / 1000).toLocaleString('en-IN', { maximumFractionDigits: 1 })}k`
  return value.toLocaleString('en-IN')
}

/* ---------------------------- Durations ------------------------------- */

/** < 60s → "Xs", else "Xm Ys" (UX rule #9). */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

/* ---------------------------- Timestamps ------------------------------ */

/** Relative time: "3 minutes ago". */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return formatDistanceToNow(d, { addSuffix: true })
}

/** HH:MM:SS wall-clock time — used in the activity feed. */
export function formatClock(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return format(d, 'HH:mm:ss')
}

export function formatFullDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return format(d, 'MMM d, yyyy \'at\' h:mm a')
}

export function formatShortDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return format(d, 'MMM d')
}

export function formatDayLabel(date: Date): string {
  return format(date, 'EEE')
}

/* ------------------------------ Strings ------------------------------- */

export function truncate(str: string | null | undefined, max: number): string {
  if (!str) return ''
  if (str.length <= max) return str
  return `${str.slice(0, max - 1).trimEnd()}…`
}

export function idShort(id: string | null | undefined): string {
  if (!id) return '—'
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}

export function parseJSONSafe(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

export function initials(name: string | null | undefined): string {
  if (!name) return '?'
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
}

/* ---------------------------- Agent metadata -------------------------- */

export interface AgentMeta {
  key: string
  label: string
  short: string
  color: string
  soft: string
  icon: LucideIcon
  model: string
}

const SOFT = (v: string) => `color-mix(in srgb, ${v} 12%, transparent)`

export const AGENT_META: Record<string, AgentMeta> = {
  planner: { key: 'planner', label: 'Planner Agent', short: 'Planner', color: 'var(--agent-planner)', soft: SOFT('var(--agent-planner)'), icon: Calendar, model: 'Claude Sonnet 4.6' },
  coder: { key: 'coder', label: 'Coder Agent', short: 'Coder', color: 'var(--agent-coder)', soft: SOFT('var(--agent-coder)'), icon: Code, model: 'Claude Sonnet 4.6' },
  tester: { key: 'tester', label: 'Tester Agent', short: 'Tester', color: 'var(--agent-tester)', soft: SOFT('var(--agent-tester)'), icon: FlaskConical, model: 'Gemini 1.5 Flash' },
  security: { key: 'security', label: 'Security Agent', short: 'Security', color: 'var(--agent-security)', soft: SOFT('var(--agent-security)'), icon: Shield, model: 'Claude Sonnet 4.6' },
  docs: { key: 'docs', label: 'Docs Agent', short: 'Docs', color: 'var(--agent-docs)', soft: SOFT('var(--agent-docs)'), icon: FileText, model: 'Gemini 1.5 Flash' },
  reviewer: { key: 'reviewer', label: 'Reviewer Agent', short: 'Reviewer', color: 'var(--agent-reviewer)', soft: SOFT('var(--agent-reviewer)'), icon: Eye, model: 'GPT-4o' },
  optimizer: { key: 'optimizer', label: 'Optimizer Agent', short: 'Optimizer', color: 'var(--agent-optimizer)', soft: SOFT('var(--agent-optimizer)'), icon: Zap, model: 'GPT-4o' },
  debugger: { key: 'debugger', label: 'Debugger Agent', short: 'Debugger', color: 'var(--agent-debugger)', soft: SOFT('var(--agent-debugger)'), icon: Bug, model: 'Claude Sonnet 4.6' },
  validator: { key: 'validator', label: 'Validator Agent', short: 'Validator', color: 'var(--agent-validator)', soft: SOFT('var(--agent-validator)'), icon: CheckCircle2, model: 'GPT-3.5 Turbo' },
  // The remaining agents registered in the backend's AGENT_LLM_MAP, so every
  // agent the API actually returns renders with a proper label and color.
  refactor: { key: 'refactor', label: 'Refactor Agent', short: 'Refactor', color: 'var(--agent-refactor)', soft: SOFT('var(--agent-refactor)'), icon: Wrench, model: 'GPT-4o' },
  summarizer: { key: 'summarizer', label: 'Summarizer Agent', short: 'Summarizer', color: 'var(--agent-summarizer)', soft: SOFT('var(--agent-summarizer)'), icon: AlignLeft, model: 'Gemini 1.5 Flash' },
  research: { key: 'research', label: 'Research Agent', short: 'Research', color: 'var(--agent-research)', soft: SOFT('var(--agent-research)'), icon: Search, model: 'Gemini 1.5 Pro' },
  hallucination_detector: { key: 'hallucination_detector', label: 'Hallucination Detector', short: 'Hallucination', color: 'var(--agent-hallucination_detector)', soft: SOFT('var(--agent-hallucination_detector)'), icon: ScanSearch, model: 'Claude Sonnet 4.6' },
  cost_controller: { key: 'cost_controller', label: 'Cost Controller', short: 'Cost', color: 'var(--agent-cost_controller)', soft: SOFT('var(--agent-cost_controller)'), icon: Wallet, model: 'GPT-3.5 Turbo' },
  hitl_controller: { key: 'hitl_controller', label: 'HITL Controller', short: 'HITL', color: 'var(--agent-hitl_controller)', soft: SOFT('var(--agent-hitl_controller)'), icon: UserCheck, model: '— (no LLM)' },
}

export function getAgentMeta(agentType: string | null | undefined): AgentMeta {
  if (agentType && AGENT_META[agentType]) return AGENT_META[agentType]
  return {
    key: agentType ?? 'unknown',
    label: agentType ? `${agentType} Agent` : 'Agent',
    short: agentType ?? 'Agent',
    color: 'var(--text-secondary)',
    soft: SOFT('var(--text-secondary)'),
    icon: CircleDashed,
    model: '—',
  }
}

export const ALL_AGENT_TYPES = Object.keys(AGENT_META)

/* ---------------------------- Status metadata ------------------------- */

export interface StatusMeta {
  label: string
  color: string
  icon: LucideIcon
}

export const STATUS_META: Record<TaskStatus, StatusMeta> = {
  pending: { label: 'Pending', color: 'var(--text-secondary)', icon: CircleDashed },
  routing: { label: 'Routing…', color: 'var(--status-info)', icon: Loader2 },
  running: { label: 'Running', color: 'var(--brand-primary)', icon: Loader2 },
  hitl_waiting: { label: 'Awaiting Approval', color: 'var(--status-warning)', icon: Bell },
  completed: { label: 'Completed', color: 'var(--status-success)', icon: CheckCircle },
  failed: { label: 'Failed', color: 'var(--status-error)', icon: XCircle },
  cancelled: { label: 'Cancelled', color: 'var(--text-secondary)', icon: Circle },
}

export function uid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `id-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

/** Extract a human-readable message from an API error (never show raw errors). */
export function apiErrorMessage(err: unknown, fallback = 'Something went wrong. Try again.'): string {
  const anyErr = err as {
    response?: { status?: number; data?: { detail?: unknown; error?: unknown; code?: unknown } }
    message?: string
    code?: string
  }
  // NexusAI's structured error shape: { error, code, request_id }
  const structured = anyErr.response?.data?.error
  if (typeof structured === 'string' && structured.length > 0) return structured
  // A locally-thrown "not supported" error carries a useful message already.
  if (anyErr.code === 'NOT_SUPPORTED' && typeof anyErr.message === 'string') {
    return anyErr.message
  }
  // No response at all → the backend is unreachable.
  if (!anyErr.response && anyErr.message === 'Network Error') {
    return 'Cannot reach the NexusAI API. Is the backend running?'
  }
  const detail = anyErr.response?.data?.detail
  if (typeof detail === 'string' && detail.length > 0) return detail
  if (typeof detail === 'object' && detail !== null) {
    // FastAPI validation errors: { detail: [{ msg, loc }] }
    try {
      const list = detail as Array<{ msg?: string; loc?: Array<string | number> }>
      if (Array.isArray(list) && list[0]?.msg) {
        return `${list[0].loc?.join('.')}: ${list[0].msg}`
      }
    } catch {
      /* fall through */
    }
  }
  if (typeof anyErr.message === 'string' && anyErr.message.length > 0) return anyErr.message
  return fallback
}
