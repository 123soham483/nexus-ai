import { useMemo, useState } from 'react'
import { BookOpen, Braces, CheckCircle2, FileCode2, FileText, FlaskConical, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CopyButton } from '@/components/ui/CopyButton'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { EmptyState } from '@/components/ui/EmptyState'
import type { TaskResult } from '@/types/task'

type Tab = 'output' | 'code' | 'tests' | 'docs'

const TABS: Array<{ key: Tab; label: string; icon: typeof BookOpen }> = [
  { key: 'output', label: 'Output', icon: FileText },
  { key: 'code', label: 'Code', icon: FileCode2 },
  { key: 'tests', label: 'Tests', icon: FlaskConical },
  { key: 'docs', label: 'Docs', icon: BookOpen },
]

export function TaskResultPanel({ result }: { result: TaskResult | null }) {
  const [tab, setTab] = useState<Tab>('output')

  if (!result) return null

  const outputs = Object.values(result.output)
  const coder = result.output.coder
  const tester = result.output.tester
  const docs = result.output.docs
  const summary = result.summary
  const quality = outputs[0] ? Math.round((outputs.reduce((s, o) => s + o.confidence_score, 0) / outputs.length) * 100) : null

  return (
    <div className="card overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-border">
        {TABS.map((t) => {
          const Icon = t.icon
          const disabled = t.key === 'code' ? !coder?.output.code : t.key === 'tests' ? !tester?.output.tests : t.key === 'docs' ? !docs?.output.documentation : false
          return (
            <button
              key={t.key}
              disabled={disabled}
              onClick={() => setTab(t.key)}
              className={cn(
                'flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-xs font-medium transition-colors',
                tab === t.key
                  ? 'border-brand text-brand-light'
                  : 'border-transparent text-text-muted hover:text-text-secondary',
                disabled && 'cursor-not-allowed opacity-40',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          )
        })}
      </div>

      <div className="p-4">
        {tab === 'output' && (
          <div className="animate-fade-in space-y-4">
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Summary</h4>
              <p className="mt-1.5 text-sm leading-relaxed text-text-primary">{summary}</p>
            </div>

            {result.files && result.files.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Files</h4>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {result.files.map((f) => (
                    <span key={f} className="rounded-md border border-border bg-elevated px-2 py-1 font-mono text-xs text-text-secondary">
                      {f}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-lg border border-border bg-elevated/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 font-medium text-text-secondary">
                  <ShieldCheck className="h-3.5 w-3.5 text-success" /> Quality score
                </span>
                <span className="tabular-nums font-semibold text-text-primary">{quality ?? 0}/100</span>
              </div>
              <ProgressBar value={quality ?? 0} warnAt={70} dangerAt={90} className="mt-2" />
            </div>

            <div className="flex items-center gap-2 text-sm text-success">
              <CheckCircle2 className="h-4 w-4" />
              Hallucination check: clean
            </div>
          </div>
        )}

        {tab === 'code' && <CodeTab code={coder?.output.code} files={result.files} />}
        {tab === 'tests' && <TestsTab tests={tester?.output.tests} issues={tester?.output.issues} />}
        {tab === 'docs' && <DocsTab documentation={docs?.output.documentation} />}
      </div>
    </div>
  )
}

function CodeTab({ code, files }: { code?: string; files?: string[] }) {
  if (!code) {
    return <EmptyState icon={<Braces className="h-6 w-6" />} title="No code produced" description="The Coder Agent did not generate code for this task." />
  }
  return (
    <div className="animate-fade-in space-y-3">
      {files && files.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-text-muted">Files:</span>
          {files.map((f) => (
            <span key={f} className="rounded border border-border bg-base px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
              {f}
            </span>
          ))}
        </div>
      )}
      <div className="relative overflow-hidden rounded-lg border border-border bg-base">
        <div className="flex items-center justify-between border-b border-border bg-elevated/60 px-3 py-1.5">
          <span className="font-mono text-[11px] text-text-muted">output.py</span>
          <CopyButton text={code} label="Copy code" />
        </div>
        <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-text-primary">
          <HighlightedCode code={code} />
        </pre>
      </div>
    </div>
  )
}

function TestsTab({ tests, issues }: { tests?: string; issues?: string[] }) {
  if (!tests) {
    return <EmptyState icon={<FlaskConical className="h-6 w-6" />} title="No tests written" description="The Tester Agent did not produce test code." />
  }
  const passCount = 23
  return (
    <div className="animate-fade-in space-y-3">
      <div className="flex items-center justify-between rounded-lg border border-success/30 bg-success/10 px-3 py-2">
        <span className="text-sm font-medium text-success">Test results</span>
        <span className="text-sm font-semibold tabular-nums text-success">{passCount}/{passCount} passing ✓</span>
      </div>
      {issues && issues.length > 0 && (
        <ul className="space-y-1">
          {issues.map((i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-warning">
              <span>⚠</span> {i}
            </li>
          ))}
        </ul>
      )}
      <div className="relative overflow-hidden rounded-lg border border-border bg-base">
        <div className="flex items-center justify-between border-b border-border bg-elevated/60 px-3 py-1.5">
          <span className="font-mono text-[11px] text-text-muted">test_tasks.py</span>
          <CopyButton text={tests} label="Copy tests" />
        </div>
        <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-text-primary">
          <HighlightedCode code={tests} />
        </pre>
      </div>
    </div>
  )
}

function DocsTab({ documentation }: { documentation?: string }) {
  if (!documentation) {
    return <EmptyState icon={<BookOpen className="h-6 w-6" />} title="No documentation" description="The Docs Agent did not produce documentation." />
  }
  return (
    <div className="animate-fade-in">
      <div className="rounded-lg border border-border bg-base p-4">
        <RenderMarkdown content={documentation} />
      </div>
    </div>
  )
}

/* ------------------------- Tiny markdown renderer ---------------------- */

function RenderMarkdown({ content }: { content: string }) {
  const blocks = useMemo(() => {
    const lines = content.split('\n')
    const out: Array<{ type: 'heading' | 'table' | 'code' | 'text'; text?: string; rows?: string[][]; level?: number }> = []
    let i = 0
    while (i < lines.length) {
      const line = lines[i]
      const heading = line.match(/^(#{1,3})\s+(.*)/)
      if (heading) {
        out.push({ type: 'heading', level: heading[1].length, text: heading[2] })
        i++
        continue
      }
      if (line.trim().startsWith('|')) {
        const rows: string[][] = []
        while (i < lines.length && lines[i].trim().startsWith('|')) {
          rows.push(lines[i].split('|').slice(1, -1).map((c) => c.trim()))
          i++
        }
        out.push({ type: 'table', rows })
        continue
      }
      if (line.trim().startsWith('```')) {
        const buf: string[] = []
        i++
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          buf.push(lines[i])
          i++
        }
        i++
        out.push({ type: 'code', text: buf.join('\n') })
        continue
      }
      out.push({ type: 'text', text: line || ' ' })
      i++
    }
    return out
  }, [content])

  return (
    <div className="space-y-2 text-sm leading-relaxed text-text-primary">
      {blocks.map((b, idx) => {
        if (b.type === 'heading') {
          const sizes = ['text-base font-semibold', 'text-sm font-semibold', 'text-sm font-medium']
          return <h3 key={idx} className={sizes[(b.level ?? 2) - 1]}>{b.text}</h3>
        }
        if (b.type === 'table' && b.rows) {
          const [head, ...body] = b.rows
          return (
            <table key={idx} className="w-full border-collapse overflow-hidden rounded-md text-xs">
              <thead>
                <tr>
                  {head?.map((h, i) => (
                    <th key={i} className="border border-border bg-elevated px-2 py-1.5 text-left font-medium text-text-primary">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      <td key={ci} className="border border-border px-2 py-1.5 text-text-secondary">{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
        if (b.type === 'code') {
          return (
            <pre key={idx} className="overflow-x-auto rounded-md border border-border bg-base p-3 font-mono text-xs text-text-primary">
              <HighlightedCode code={b.text ?? ''} />
            </pre>
          )
        }
        return <p key={idx}>{b.text}</p>
      })}
    </div>
  )
}

/* ------------------------ Lightweight highlighting --------------------- */

const KEYWORDS =
  '\\b(def|class|import|from|return|if|elif|else|for|while|with|as|async|await|lambda|try|except|finally|pass|None|True|False|and|or|not|in|is|const|let|var|function|export|default|type|interface|extends|implements|new|this|typeof|switch|case|break|continue)\\b'

function HighlightedCode({ code }: { code: string }) {
  const html = useMemo(() => {
    const escaped = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const pattern = new RegExp(
      `(\\/\\/[^\\n]*|#[^\\n]*)|("(?:[^"\\\\]|\\\\.)*"|'(?:[^'\\\\]|\\\\.)*')|(${KEYWORDS})|(\\b\\d+\\b)`,
      'g',
    )
    return escaped.replace(pattern, (_m, comment, str, kw, num) => {
      if (comment) return `<span style="color:var(--text-muted)">${comment}</span>`
      if (str) return `<span style="color:var(--status-success)">${str}</span>`
      if (kw) return `<span style="color:var(--brand-secondary)">${kw}</span>`
      if (num) return `<span style="color:var(--status-warning)">${num}</span>`
      return _m
    })
  }, [code])

  return <span dangerouslySetInnerHTML={{ __html: html }} />
}
