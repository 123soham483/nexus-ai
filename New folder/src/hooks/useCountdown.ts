import { useEffect, useState } from 'react'

/** Ticks every second toward expiresAt; returns remaining seconds. */
export function useCountdown(expiresAt: string | undefined): number {
  const calc = () => {
    if (!expiresAt) return 0
    return Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000))
  }
  const [remaining, setRemaining] = useState(calc)

  useEffect(() => {
    setRemaining(calc())
    const t = window.setInterval(() => setRemaining(calc()), 1000)
    return () => window.clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expiresAt])

  return remaining
}

export function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}
