import { WifiOff } from 'lucide-react'
import { useConnectionStore } from '@/store/connectionStore'

export function ConnectionBanner() {
  const status = useConnectionStore((s) => s.status)
  if (status !== 'reconnecting' && status !== 'connecting') return null

  return (
    <div className="sticky top-14 z-30 flex items-center justify-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-xs font-medium text-warning">
      <WifiOff className="h-3.5 w-3.5 animate-pulse" />
      {status === 'connecting' ? 'Connecting to live stream…' : 'Reconnecting…'}
    </div>
  )
}
