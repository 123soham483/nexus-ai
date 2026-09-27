import { useState } from 'react'
import { Brain, SearchX, Trash2 } from 'lucide-react'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { MemorySearchBar } from '@/components/memory/MemorySearchBar'
import { MemoryResultCard } from '@/components/memory/MemoryResultCard'
import { FailurePatternCard } from '@/components/memory/FailurePatternCard'
import { cn } from '@/lib/utils'
import { useMemorySearch, useFailurePatterns, useClearMemory } from '@/hooks/useMemory'

type Tab = 'memories' | 'failures'

export function MemoryPage() {
  const [tab, setTab] = useState<Tab>('memories')
  const [searched, setSearched] = useState('')
  const [confirmClear, setConfirmClear] = useState(false)
  const {
    data: results,
    isFetching: searching,
    isError: searchFailed,
    refetch: retrySearch,
  } = useMemorySearch(searched, searched.length > 0)
  const {
    data: failures,
    isLoading: failuresLoading,
    isError: failuresFailed,
    refetch: retryFailures,
  } = useFailurePatterns()
  const clearMemory = useClearMemory()

  const hasSearched = searched.length > 0

  return (
    <PageWrapper>
      <MemorySearchBar
        loading={searching}
        onSearch={(q) => setSearched(q)}
      />

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg border border-border bg-elevated/50 p-0.5">
          {(
            [
              { key: 'memories', label: 'Task Memories' },
              { key: 'failures', label: 'Failure Patterns' },
            ] as Array<{ key: Tab; label: string }>
          ).map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                'rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors',
                tab === t.key ? 'bg-brand text-[#06281c]' : 'text-text-secondary hover:text-text-primary',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <Button variant="danger" size="sm" onClick={() => setConfirmClear(true)}>
          <Trash2 className="h-3.5 w-3.5" /> Clear All Memory
        </Button>
      </div>

      <div className="mt-4">
        {tab === 'memories' ? (
          <>
            {!hasSearched ? (
              <Card>
                <EmptyState
                  icon={<Brain className="h-6 w-6" />}
                  title="Search your agents' memory"
                  description="NexusAI stores what worked (and what didn't) on every task. Search by meaning to find reusable patterns."
                />
              </Card>
            ) : searchFailed ? (
              <Card>
                <ErrorState
                  message="Memory search is unavailable — the vector store could not be reached."
                  onRetry={() => void retrySearch()}
                />
              </Card>
            ) : searching ? (
              <div className="space-y-3">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-28 w-full" />
                ))}
              </div>
            ) : results && results.length > 0 ? (
              <div className="grid gap-3 md:grid-cols-2">
                {results.map((r, i) => (
                  <MemoryResultCard key={i} result={r} />
                ))}
              </div>
            ) : (
              <Card>
                <EmptyState
                  icon={<SearchX className="h-6 w-6" />}
                  title={`No memories match “${searched}”`}
                  description="Try different wording — search matches meaning, not keywords."
                />
              </Card>
            )}
          </>
        ) : failuresFailed ? (
          <Card>
            <ErrorState
              message="Could not load failure patterns — the vector store could not be reached."
              onRetry={() => void retryFailures()}
            />
          </Card>
        ) : failuresLoading || !failures ? (
          <div className="grid gap-3 md:grid-cols-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-36 w-full" />
            ))}
          </div>
        ) : failures.length === 0 ? (
          <Card>
            <EmptyState
              icon={<Brain className="h-6 w-6" />}
              title="No failure patterns stored"
              description="When tasks fail, NexusAI records the pattern here so future runs can avoid it."
            />
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {failures.map((f) => (
              <FailurePatternCard key={f.id} pattern={f} />
            ))}
          </div>
        )}
      </div>

      <Modal
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        title="Clear all memory?"
        description="This permanently deletes all task memories and failure patterns. Agents will lose learned context."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmClear(false)}>
              Keep memory
            </Button>
            <Button
              variant="danger"
              loading={clearMemory.isPending}
              onClick={() =>
                clearMemory.mutate(undefined, {
                  onSuccess: () => {
                    setConfirmClear(false)
                    setSearched('')
                  },
                })
              }
            >
              Clear all memory
            </Button>
          </>
        }
      >
        <p className="text-sm text-text-secondary">
          This action cannot be undone. Consider that failure patterns protect future tasks from repeating mistakes.
        </p>
      </Modal>
    </PageWrapper>
  )
}
