import { useState } from 'react'
import { Search, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/Button'

export interface MemorySearchBarProps {
  onSearch: (query: string) => void
  loading?: boolean
}

export function MemorySearchBar({ onSearch, loading }: MemorySearchBarProps) {
  const [query, setQuery] = useState('')

  const submit = () => {
    if (query.trim().length > 0) onSearch(query.trim())
  }

  return (
    <div className="card p-4">
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            placeholder="Search your agent's memory… e.g. 'authentication patterns'"
            className="input pl-9"
          />
        </div>
        <Button loading={loading} onClick={submit}>
          <Search className="h-4 w-4" /> Search Memory
        </Button>
      </div>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
        <Sparkles className="h-3 w-3 text-brand" />
        Search by meaning, not keywords. “JWT auth” finds “login token implementation”.
      </p>
    </div>
  )
}
