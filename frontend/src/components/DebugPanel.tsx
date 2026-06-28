import { useEffect, useMemo, useRef, useState } from 'react'
import { Bug, ChevronDown, Copy, Trash2, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type DebugEventType =
  | 'meta'
  | 'phase'
  | 'tool_call'
  | 'tool_result'
  | 'llm_call'
  | 'llm_response'
  | 'done'
  | 'error'

export type DebugEvent = {
  ts: number
  type: DebugEventType
  payload: unknown
}

type Props = {
  events: DebugEvent[]
  open: boolean
  onClose: () => void
  onClear: () => void
}

const ALL_TYPES: DebugEventType[] = [
  'meta',
  'phase',
  'llm_call',
  'llm_response',
  'tool_call',
  'tool_result',
  'done',
  'error',
]

const TYPE_COLORS: Record<DebugEventType, string> = {
  meta: 'text-slate-400',
  phase: 'text-slate-400',
  llm_call: 'text-violet-300',
  llm_response: 'text-violet-300',
  tool_call: 'text-sky-300',
  tool_result: 'text-emerald-300',
  done: 'text-zinc-300',
  error: 'text-rose-300',
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${hh}:${mm}:${ss}.${ms}`
}

function summarize(ev: DebugEvent): string {
  const p = ev.payload as Record<string, unknown> | null
  if (!p || typeof p !== 'object') return JSON.stringify(p)
  switch (ev.type) {
    case 'meta':
      return `model=${p.model as string} asst_id=${p.assistant_message_id as number}`
    case 'phase':
      return `phase=${p.phase as string}`
    case 'llm_call':
      return `iter=${p.iteration as number} model=${p.model as string} msgs=${p.messages_count as number} chars=${p.total_chars as number}`
    case 'llm_response':
      return `iter=${p.iteration as number} finish=${p.finish_reason as string} text=${p.text_chars as number}c tools=${p.tool_calls_count as number} ${p.duration_ms as number}ms`
    case 'tool_call':
      return `${p.name as string} id=${String(p.id as string).slice(0, 8)} args=${JSON.stringify(p.arguments)}`
    case 'tool_result':
      return `${p.tool as string} ok=${p.ok as boolean} ${p.duration_ms as number}ms ${(p.description as string | undefined) ?? ''}`
    case 'done':
      return `model=${p.model as string} ${(p.latency_ms as number | null) ?? '?'}ms tools=${((p.tools as string[] | undefined) ?? []).join(',')}`
    case 'error':
      return `code=${(p.code as number | string | null) ?? '?'} ${p.message as string}`
    default:
      return JSON.stringify(p)
  }
}

function copyText(text: string): void {
  if (typeof navigator !== 'undefined' && navigator.clipboard) {
    void navigator.clipboard.writeText(text).catch(() => {
      /* ignore */
    })
    return
  }
  // Fallback para contextos sin clipboard API
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.style.position = 'fixed'
    el.style.opacity = '0'
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
  } catch {
    /* ignore */
  }
}

export default function DebugPanel({ events, open, onClose, onClear }: Props) {
  const [filter, setFilter] = useState<Set<DebugEventType>>(() => new Set(ALL_TYPES))
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [stuck, setStuck] = useState(false)

  const stats = useMemo(() => {
    let iterations = 0
    const tools = new Set<string>()
    let errors = 0
    let totalLatency: number | null = null
    let model: string | null = null
    for (const ev of events) {
      const p = ev.payload as Record<string, unknown> | null
      if (ev.type === 'llm_call' && p) {
        iterations = Math.max(iterations, (p.iteration as number) ?? 0)
        model = (p.model as string) ?? model
      }
      if (ev.type === 'tool_call' && p) {
        const name = p.name as string | undefined
        if (name) tools.add(name)
      }
      if (ev.type === 'tool_result' && p && p.ok === false) errors++
      if (ev.type === 'done' && p) {
        const lat = p.latency_ms
        if (typeof lat === 'number') totalLatency = lat
        if (typeof p.model === 'string') model = p.model
      }
    }
    return {
      iterations,
      tools: Array.from(tools),
      errors,
      totalLatency,
      model,
    }
  }, [events])

  // Auto-scroll al final cuando hay eventos nuevos (a menos que el
  // usuario se haya scrolleado hacia arriba para inspeccionar algo).
  useEffect(() => {
    if (!open || stuck) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [events, open, stuck])

  function onScroll(): void {
    const el = scrollRef.current
    if (!el) return
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setStuck(!isAtBottom)
  }

  function toggleFilter(t: DebugEventType): void {
    setFilter((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
  }

  const filtered = useMemo(
    () => events.filter((e) => filter.has(e.type)),
    [events, filter],
  )

  function onCopy(): void {
    const text = filtered
      .map((ev) => `[${formatTime(ev.ts)}] ${ev.type} ${JSON.stringify(ev.payload)}`)
      .join('\n')
    copyText(text)
  }

  function jumpToLatest(): void {
    setStuck(false)
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }

  if (!open) return null

  return (
    <div
      className="relative shrink-0 border-t bg-zinc-950 text-zinc-100 font-mono text-[11px] flex flex-col"
      style={{ height: 260 }}
      data-testid="debug-panel"
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 shrink-0 overflow-x-auto">
        <Bug className="size-3 text-zinc-400 shrink-0" aria-hidden />
        <span className="text-xs font-semibold text-zinc-200 shrink-0">Debug log</span>
        {stats.model && (
          <span className="text-[10px] text-zinc-400 shrink-0">model: {stats.model}</span>
        )}
        {stats.iterations > 0 && (
          <span className="text-[10px] text-zinc-400 shrink-0">
            iters: {stats.iterations}
          </span>
        )}
        {stats.tools.length > 0 && (
          <span className="text-[10px] text-zinc-400 shrink-0">
            tools: {stats.tools.join(', ')}
          </span>
        )}
        {stats.totalLatency != null && (
          <span className="text-[10px] text-zinc-400 shrink-0">
            latency: {stats.totalLatency}ms
          </span>
        )}
        {stats.errors > 0 && (
          <span className="text-[10px] text-rose-300 shrink-0">{stats.errors} err</span>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-1 shrink-0">
          {ALL_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => toggleFilter(t)}
              className={cn(
                'px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider transition',
                filter.has(t)
                  ? 'bg-zinc-700 text-zinc-100'
                  : 'bg-zinc-900 text-zinc-500 line-through',
              )}
              title={`${filter.has(t) ? 'Ocultar' : 'Mostrar'} eventos ${t}`}
            >
              {t}
            </button>
          ))}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onCopy}
          className="size-6 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
          aria-label="Copiar log"
        >
          <Copy className="size-3" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClear}
          className="size-6 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
          aria-label="Limpiar log"
        >
          <Trash2 className="size-3" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="size-6 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
          aria-label="Cerrar panel"
        >
          <X className="size-3" />
        </Button>
      </div>
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-0.5"
      >
        {filtered.length === 0 && (
          <p className="text-zinc-500 italic">Esperando eventos…</p>
        )}
        {filtered.map((ev, i) => (
          <div
            key={`${ev.ts}-${i}`}
            className="flex items-start gap-2"
            data-event-type={ev.type}
          >
            <span className="text-zinc-500 shrink-0 tabular-nums">{formatTime(ev.ts)}</span>
            <span
              className={cn(
                'shrink-0 uppercase tracking-wider text-[9px] font-semibold w-24 truncate',
                TYPE_COLORS[ev.type],
              )}
            >
              {ev.type}
            </span>
            <span className="flex-1 min-w-0 break-all text-zinc-200">{summarize(ev)}</span>
          </div>
        ))}
      </div>
      {stuck && (
        <Button
          type="button"
          size="icon"
          onClick={jumpToLatest}
          className="absolute right-3 bottom-3 size-7 rounded-full shadow-lg"
          aria-label="Ir al final"
        >
          <ChevronDown className="size-4" />
        </Button>
      )}
    </div>
  )
}
