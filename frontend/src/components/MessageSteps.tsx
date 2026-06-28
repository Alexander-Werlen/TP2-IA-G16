import { Check, Loader2, X } from 'lucide-react'
import { memo } from 'react'

import { cn } from '@/lib/utils'

export type StepStatus = 'running' | 'ok' | 'error'

export type MessageStep = {
  id: string
  name: string
  description: string
  display_args: Record<string, unknown>
  status: StepStatus
  duration_ms?: number
}

type Props = {
  steps: MessageStep[]
  compact?: boolean
  className?: string
}

function formatDuration(ms: number | undefined): string | null {
  if (ms == null || ms < 0) return null
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function StatusIcon({ status }: { status: StepStatus }) {
  if (status === 'running') {
    return <Loader2 className="size-3 animate-spin text-muted-foreground" aria-hidden />
  }
  if (status === 'error') {
    return <X className="size-3 text-destructive" aria-hidden />
  }
  return <Check className="size-3 text-emerald-600 dark:text-emerald-400" aria-hidden />
}

function formatDisplayValue(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function MessageStepsImpl({ steps, compact = false, className }: Props) {
  if (steps.length === 0) return null
  return (
    <div
      className={cn(
        'flex flex-col gap-1 text-[11px] text-muted-foreground',
        compact && 'opacity-70',
        className,
      )}
    >
      {steps.map((s) => {
        const dur = formatDuration(s.duration_ms)
        return (
          <div
            key={s.id}
            className="flex items-start gap-1.5"
            data-status={s.status}
            data-tool={s.name}
          >
            <span className="mt-0.5 shrink-0">
              <StatusIcon status={s.status} />
            </span>
            <span className="flex-1 min-w-0">
              <span className={cn('block truncate', s.status === 'error' && 'text-destructive')}>
                {s.description}
              </span>
              {!compact && Object.keys(s.display_args).length > 0 && (
                <span className="block font-mono text-[10px] opacity-70 truncate">
                  {Object.entries(s.display_args)
                    .map(([k, v]) => `${k}=${formatDisplayValue(v)}`)
                    .join(' · ')}
                </span>
              )}
            </span>
            {dur && (
              <span className="shrink-0 tabular-nums text-[10px] opacity-60">{dur}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

export const MessageSteps = memo(MessageStepsImpl)
