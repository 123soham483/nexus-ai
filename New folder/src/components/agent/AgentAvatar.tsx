import { cn, getAgentMeta } from '@/lib/utils'

const SIZES = {
  sm: 'h-6 w-6 text-[10px]',
  md: 'h-8 w-8 text-xs',
  lg: 'h-10 w-10 text-sm',
}

export interface AgentAvatarProps {
  agentType: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
  title?: string
}

export function AgentAvatar({ agentType, size = 'md', className, title }: AgentAvatarProps) {
  const meta = getAgentMeta(agentType)
  const Icon = meta.icon
  return (
    <span
      title={title ?? meta.label}
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full border transition-transform',
        SIZES[size],
        className,
      )}
      style={{
        background: meta.soft,
        borderColor: `color-mix(in srgb, ${meta.color} 35%, transparent)`,
        color: meta.color,
      }}
    >
      <Icon className="h-[55%] w-[55%]" />
    </span>
  )
}
