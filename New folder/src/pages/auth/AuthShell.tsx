import type { ReactNode } from 'react'
import { Bot, Brain, Code2, Cpu, FlaskConical, Layers, Shield, Workflow, Zap } from 'lucide-react'

const FLOATERS = [
  { icon: Code2, color: 'var(--agent-coder)', delay: '0s', x: '8%', y: '18%' },
  { icon: FlaskConical, color: 'var(--agent-tester)', delay: '1.2s', x: '72%', y: '12%' },
  { icon: Shield, color: 'var(--agent-security)', delay: '0.6s', x: '84%', y: '55%' },
  { icon: Brain, color: 'var(--agent-planner)', delay: '1.8s', x: '12%', y: '64%' },
  { icon: Cpu, color: 'var(--agent-validator)', delay: '2.4s', x: '58%', y: '78%' },
  { icon: Zap, color: 'var(--agent-optimizer)', delay: '0.9s', x: '30%', y: '88%' },
  { icon: Layers, color: 'var(--agent-reviewer)', delay: '1.5s', x: '88%', y: '82%' },
  { icon: Workflow, color: 'var(--agent-docs)', delay: '2.1s', x: '44%', y: '6%' },
]

const BULLETS = [
  { icon: Bot, text: '15 specialized agents working in parallel' },
  { icon: Cpu, text: 'Real-time cost tracking, pre-task estimates' },
  { icon: Workflow, text: 'Full execution trace for every decision' },
]

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid-backdrop relative flex min-h-screen items-center justify-center p-4">
      <div className="relative z-10 grid w-full max-w-5xl overflow-hidden rounded-2xl border border-border bg-surface shadow-card md:grid-cols-2">
        {/* Branding panel (desktop) */}
        <div className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-base/60 p-10 md:flex">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-brand-light to-brand text-lg font-bold text-[#06281c]">
              N
            </span>
            <span className="text-gradient-gold font-display text-2xl font-bold tracking-wide">
              NexusAI
            </span>
          </div>

          <div className="relative">
            <h1 className="font-display text-3xl font-bold leading-snug text-text-primary">
              Your AI team,
              <br />
              <span className="text-gradient-gold">always on.</span>
            </h1>
            <ul className="mt-6 space-y-3.5">
              {BULLETS.map((b) => {
                const Icon = b.icon
                return (
                  <li key={b.text} className="flex items-center gap-3 text-sm text-text-secondary">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-elevated text-brand-light">
                      <Icon className="h-4 w-4" />
                    </span>
                    {b.text}
                  </li>
                )
              })}
            </ul>
          </div>

          <p className="text-xs text-text-muted">Mission control for multi-agent development</p>

          {/* Floating agent badges */}
          {FLOATERS.map((f, i) => {
            const Icon = f.icon
            return (
              <span
                key={i}
                className="pointer-events-none absolute animate-float rounded-xl border p-2.5 opacity-70"
                style={{
                  left: f.x,
                  top: f.y,
                  color: f.color,
                  borderColor: `color-mix(in srgb, ${f.color} 35%, transparent)`,
                  background: `color-mix(in srgb, ${f.color} 8%, transparent)`,
                  animationDelay: f.delay,
                }}
              >
                <Icon className="h-4 w-4" />
              </span>
            )
          })}
        </div>

        {/* Form panel */}
        <div className="flex flex-col justify-center p-6 sm:p-10">
          <div className="mb-6 flex items-center gap-2.5 md:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-brand-light to-brand font-bold text-[#06281c]">N</span>
            <span className="text-gradient-gold font-display text-xl font-bold">NexusAI</span>
          </div>
          {children}
        </div>
      </div>
    </div>
  )
}
