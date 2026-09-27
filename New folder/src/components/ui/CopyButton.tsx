import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import toast from 'react-hot-toast'
import { Tooltip } from '@/components/ui/Tooltip'

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      toast.success('Copied to clipboard')
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('Could not copy')
    }
  }

  return (
    <Tooltip label={copied ? 'Copied!' : label}>
      <button
        onClick={copy}
        className="rounded-md p-1 text-text-muted transition-colors hover:bg-elevated hover:text-text-primary"
        aria-label={label}
      >
        {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </Tooltip>
  )
}
