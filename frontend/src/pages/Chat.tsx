import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bug, Loader2, Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { MessageSteps, type MessageStep } from '@/components/MessageSteps'
import DebugPanel, { type DebugEvent, type DebugEventType } from '@/components/DebugPanel'
import {
  getCarrera,
  listChats,
  listMessages,
  streamMessage,
  type Carrera,
  type Chat,
  type Message,
  type Modulo,
  type StreamError,
  type StreamPhase,
  type StreamToolCall,
  type StreamToolResult,
} from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { Markdown, stripCitations } from '@/components/Markdown'

// (TOOL_LABELS ya no se usa en este archivo: la descripción humana
// viene del backend en ``tool_call.description`` y ``tool_result.description``.)
// Modelos permitidos (whitelisteados server-side en Settings.allowed_models).
// Mantener sincronizado con backend/app/config.py.
const ALLOWED_MODELS = [
  'deepseek-v4-flash',
  'glm-5.2',
] as const
const DEFAULT_MODEL = 'deepseek-v4-flash'
const MODEL_STORAGE_KEY = 'tutoria:selectedModel'
const DEBUG_OPEN_STORAGE_KEY = 'tutoria:debugOpen'

function loadStoredModel(): string {
  try {
    const stored = localStorage.getItem(MODEL_STORAGE_KEY)
    if (stored && (ALLOWED_MODELS as readonly string[]).includes(stored)) {
      return stored
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_MODEL
}

function loadStoredDebugOpen(): boolean {
  try {
    if (localStorage.getItem(DEBUG_OPEN_STORAGE_KEY) === '1') return true
  } catch {
    /* ignore */
  }
  return false
}

function pushDebug(setter: (updater: (prev: DebugEvent[]) => DebugEvent[]) => void, type: DebugEventType, payload: unknown): void {
  setter((prev) => [...prev, { ts: Date.now(), type, payload }])
}

type LocalMessage = Message & {
  _pending?: boolean
  _error?: boolean
  _phase?: 'thinking' | 'tools' | 'answering' | string
  _tools?: string[]
  _steps?: MessageStep[]
}

export default function ChatPage() {
  const params = useParams()
  const qc = useQueryClient()
  const user = useAuthStore((s) => s.user)

  const chatId = Number(params.chatId)
  const validChatId = Number.isFinite(chatId) && chatId > 0

  const [selectedModel, setSelectedModel] = useState<string>(loadStoredModel)
  const [debugOpen, setDebugOpen] = useState<boolean>(loadStoredDebugOpen)
  const [debugLog, setDebugLog] = useState<DebugEvent[]>([])

  const carreraQuery = useQuery<Carrera>({
    queryKey: ['carrera'],
    queryFn: getCarrera,
  })
  const chatsQuery = useQuery({
    queryKey: ['chats'],
    queryFn: () => listChats(),
    enabled: validChatId,
  })
  const messagesQuery = useQuery({
    queryKey: ['messages', chatId],
    queryFn: () => listMessages(chatId),
    enabled: validChatId,
  })

  // Mensajes "en vuelo" (optimistic + streaming en curso) que se superponen
  // al historial del backend hasta que se reconcilian.
  const [live, setLive] = useState<LocalMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [streamError, setStreamError] = useState<string | null>(null)
  const streamController = useRef<AbortController | null>(null)

  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const el = listRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [live.length, messagesQuery.data?.items.length, streaming])

  // Cancelar el stream en curso si el componente se desmonta.
  useEffect(() => {
    return () => {
      streamController.current?.abort()
      streamController.current = null
    }
  }, [])

  // Al cambiar de chat, abortar cualquier stream en curso y resetear el
  // estado local (mensajes "live" optimistas/streaming, banners de error,
  // input, etc.) para que no se filtre contenido de un chat anterior al
  // nuevo. El historial persistido lo maneja React Query por chatId.
  useEffect(() => {
    streamController.current?.abort()
    streamController.current = null
    setLive([])
    setStreaming(false)
    setStreamError(null)
    setDraft('')
    setDebugLog([])
  }, [chatId])

  const chat = useMemo<Chat | undefined>(
    () => chatsQuery.data?.items.find((c) => c.id === chatId),
    [chatsQuery.data, chatId],
  )

  const breadcrumb = useMemo(() => {
    if (!chat || !carreraQuery.data) return null
    const modulosQueryState = qc.getQueryData<{ items: Modulo[] }>(['modulos'])
    const modulo = modulosQueryState?.items.find((m) => m.id === chat.modulo_id)
    if (!modulo) return null
    const year = carreraQuery.data.years.find((y) => y.year === modulo.materia_year)
    if (!year) return null
    const materia = year.materias.find((m) => m.id === modulo.materia_id)
    if (!materia) return null
    return { year: year.name, materia: materia.name, modulo: modulo.name }
  }, [chat, carreraQuery.data, qc])

  function onModelChange(value: string) {
    setSelectedModel(value)
    try {
      localStorage.setItem(MODEL_STORAGE_KEY, value)
    } catch {
      /* ignore */
    }
  }

  function onDebugToggle() {
    setDebugOpen((prev) => {
      const next = !prev
      try {
        localStorage.setItem(DEBUG_OPEN_STORAGE_KEY, next ? '1' : '0')
      } catch {
        /* ignore */
      }
      return next
    })
  }

  function onDebugClear() {
    setDebugLog([])
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const content = draft.trim()
    if (!content || streaming) return
    setDraft('')
    setStreamError(null)
    setDebugLog([])

    const tempId = -Date.now()
    const userMsg: LocalMessage = {
      id: tempId,
      chat_id: chatId,
      role: 'user',
      content,
      model_used: null,
      created_at: new Date().toISOString(),
    }
    const assistantMsg: LocalMessage = {
      id: tempId - 1,
      chat_id: chatId,
      role: 'assistant',
      content: '',
      model_used: selectedModel,
      created_at: new Date().toISOString(),
      _pending: true,
    }
    setLive([userMsg, assistantMsg])
    setStreaming(true)

    let currentText = ''
    // Referencia mutable al id del assistant en el state. Se actualiza
    // apenas llega el meta y, a partir de ahí, todos los handlers (tools,
    // token, done) matchean por ESTA referencia, no por el id temporal
    // del mensaje (que ya fue reemplazado). Es importante que
    // ``onTools`` y ``onToken`` usen este mismo id: como React 18
    // batchea los ``setLive`` concurrentes, no podemos confiar en que el
    // id real (``meta.assistant_message_id``) esté en el ``prev`` que
    // recibe el siguiente handler — puede estar todavía con el id
    // temporal.
    let assistantStateId: number = assistantMsg.id

    streamController.current = streamMessage(
      chatId,
      { content, model: selectedModel },
      {
        onMeta: (data) => {
          assistantStateId = data.assistant_message_id
          pushDebug(setDebugLog, 'meta', data)
          setLive((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id
                ? { ...m, id: data.assistant_message_id, model_used: data.model }
                : m.id === userMsg.id
                ? { ...m, id: data.user_message_id }
                : m,
            ),
          )
        },
        onPhase: (data: StreamPhase) => {
          pushDebug(setDebugLog, 'phase', data)
          setLive((prev) => {
            const targetId =
              assistantStateId !== assistantMsg.id ? assistantStateId : assistantMsg.id
            return prev.map((m) => (m.id === targetId ? { ...m, _phase: data.phase } : m))
          })
        },
        onLlmCall: (data) => {
          pushDebug(setDebugLog, 'llm_call', data)
        },
        onLlmResponse: (data) => {
          pushDebug(setDebugLog, 'llm_response', data)
        },
        onToolCall: (data: StreamToolCall) => {
          if (typeof window !== 'undefined' && (window as { __TUTORIA_DEBUG__?: boolean }).__TUTORIA_DEBUG__) {
            console.debug('[tutoria] onToolCall', data)
          }
          pushDebug(setDebugLog, 'tool_call', data)
          setLive((prev) => {
            const targetId =
              assistantStateId !== assistantMsg.id ? assistantStateId : assistantMsg.id
            return prev.map((m) => {
              if (m.id !== targetId) return m
              const steps = m._steps ?? []
              return {
                ...m,
                _phase: 'tools' as const,
                _steps: [
                  ...steps,
                  {
                    id: data.id,
                    name: data.name,
                    description: data.description,
                    display_args: data.display_args ?? {},
                    status: 'running' as const,
                  },
                ],
              }
            })
          })
        },
        onToolResult: (data: StreamToolResult) => {
          if (typeof window !== 'undefined' && (window as { __TUTORIA_DEBUG__?: boolean }).__TUTORIA_DEBUG__) {
            console.debug('[tutoria] onToolResult', data)
          }
          pushDebug(setDebugLog, 'tool_result', data)
          setLive((prev) => {
            const targetId =
              assistantStateId !== assistantMsg.id ? assistantStateId : assistantMsg.id
            return prev.map((m) => {
              if (m.id !== targetId) return m
              const steps = m._steps ?? []
              // Buscamos el step por nombre+status=running (puede haber
              // varios con el mismo nombre si el LLM insiste). Tomamos el
              // último running con ese nombre para no marcar varios.
              let matched = false
              const updated = steps.map((s) => {
                if (!matched && s.name === data.tool && s.status === 'running') {
                  matched = true
                  return {
                    ...s,
                    status: (data.ok ? 'ok' : 'error') as 'ok' | 'error',
                    duration_ms: data.duration_ms,
                    description: data.description || s.description,
                  }
                }
                return s
              })
              return { ...m, _steps: updated }
            })
          })
        },
        onToken: (token) => {
          currentText += token
          setLive((prev) => {
            const targetId =
              assistantStateId !== assistantMsg.id ? assistantStateId : assistantMsg.id
            return prev.map((m) =>
              m.id === targetId
                ? { ...m, content: currentText, _phase: 'answering' as const }
                : m,
            )
          })
        },
        onDone: (data) => {
          pushDebug(setDebugLog, 'done', data)
          setStreaming(false)
          streamController.current = null
          void qc.invalidateQueries({ queryKey: ['messages', chatId] })
        },
        onError: (err: StreamError) => {
          pushDebug(setDebugLog, 'error', err)
          setStreaming(false)
          streamController.current = null
          setStreamError(err.message)
          setLive((prev) => {
            const targetId =
              assistantStateId !== assistantMsg.id ? assistantStateId : assistantMsg.id
            return prev.map((m) =>
              m.id === targetId
                ? {
                    ...m,
                    content: currentText || `[error] ${err.message}`,
                    _pending: false,
                    _error: true,
                    _phase: undefined,
                  }
                : m,
            )
          })
        },
      },
    )
  }

  // Mensajes a renderizar: historial del backend + mensajes en vuelo
  // (filtramos para no duplicar con los que ya estén persistidos).
  // Cuando un mensaje en ``live`` tiene ``_steps`` y el backend lo
  // devuelve ya persistido, copiamos ``_steps`` al item del backend
  // para que el panel de pasos no desaparezca al revalidar la query.
  const renderedMessages: LocalMessage[] = useMemo(() => {
    const persisted: LocalMessage[] = (messagesQuery.data?.items ?? []).map((p) => {
      const matchingLive = live.find((lm) => lm.id === p.id)
      if (matchingLive) {
        return {
          ...p,
          _steps: matchingLive._steps ?? (p as LocalMessage)._steps,
        }
      }
      return p
    })
    const liveFiltered = live.filter(
      (lm) => !persisted.some((p) => p.id === lm.id),
    )
    return [...persisted, ...liveFiltered]
  }, [messagesQuery.data, live])

  if (!validChatId) {
    return (
      <div className="flex-1 flex items-center justify-center p-4">
        <p className="text-sm text-destructive">Chat inválido.</p>
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <header className="border-b shrink-0">
        <div className="px-4 py-3 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <h1 className="text-base font-semibold truncate">
              {chat?.title ?? (chatsQuery.isLoading ? 'Cargando…' : 'Chat')}
            </h1>
            {breadcrumb && (
              <p className="text-xs text-muted-foreground truncate">
                {breadcrumb.year} · {breadcrumb.materia} · {breadcrumb.modulo}
              </p>
            )}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="hidden sm:inline">Modelo</span>
            <select
              value={selectedModel}
              onChange={(e) => onModelChange(e.target.value)}
              disabled={streaming}
              className="text-xs rounded-md border bg-background px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring"
              aria-label="Modelo LLM"
            >
              {ALLOWED_MODELS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <Button
            type="button"
            variant={debugOpen ? 'secondary' : 'ghost'}
            size="icon"
            onClick={onDebugToggle}
            className="size-8"
            aria-label={debugOpen ? 'Ocultar log de debug' : 'Mostrar log de debug'}
            title={debugOpen ? 'Ocultar log de debug' : 'Mostrar log de debug'}
            data-testid="debug-toggle"
          >
            <Bug className="size-4" />
          </Button>
        </div>
      </header>

      <section className="flex-1 min-h-0 px-4 py-4 flex flex-col gap-4">
        <Card className="flex-1 min-h-0 flex flex-col">
          <CardHeader className="pb-2 shrink-0">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Conversación
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 min-h-0 flex flex-col gap-3">
            <div
              ref={listRef}
              className="flex-1 min-h-0 overflow-y-auto rounded border bg-card/40 p-3 space-y-3"
            >
              {messagesQuery.isLoading && (
                <p className="text-sm text-muted-foreground">Cargando mensajes…</p>
              )}
              {messagesQuery.error && (
                <p className="text-sm text-destructive">No se pudo cargar el historial.</p>
              )}
              {messagesQuery.data && messagesQuery.data.items.length === 0 && live.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  Aún no hay mensajes. Escribí el primero abajo.
                </p>
              )}
              {renderedMessages.map((m) => (
                <MessageBubble key={`${m.id}-${m.created_at}`} message={m} />
              ))}
              {streamError && (
                <p className="text-sm text-destructive">{streamError}</p>
              )}
            </div>

            <form onSubmit={onSubmit} className="flex items-center gap-2 shrink-0">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={`Escribí un mensaje a TutorIA… (${user?.name ?? 'estudiante'})`}
                disabled={streaming}
                autoFocus
              />
              <Button type="submit" disabled={streaming || !draft.trim()}>
                <Send className="size-4" />
                {streaming ? '…' : 'Enviar'}
              </Button>
            </form>
            <p className="text-xs text-muted-foreground shrink-0">
              Fase 6: agente con LangGraph + tools + memoria. Modelo activo:&nbsp;
              <code className="font-mono">{selectedModel}</code>.
            </p>
          </CardContent>
        </Card>
        <DebugPanel
          events={debugLog}
          open={debugOpen}
          onClose={onDebugToggle}
          onClear={onDebugClear}
        />
      </section>
    </div>
  )
}

function MessageBubble({ message }: { message: LocalMessage }) {
  const isUser = message.role === 'user'
  const bubbleClass = isUser
    ? 'bg-primary text-primary-foreground whitespace-pre-wrap'
    : message._error
    ? 'bg-destructive/10 text-destructive border border-destructive/30 break-words'
    : 'bg-muted text-foreground border break-words'
  const steps = message._steps ?? []
  const hasSteps = !isUser && steps.length > 0
  const showStepsCompact = hasSteps && message._phase === 'answering' && !!message.content
  const showPhasePlaceholder =
    !isUser && message._pending && !message.content && steps.length === 0
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${bubbleClass}`}>
        <div className="flex items-center gap-2 mb-0.5 text-[10px] uppercase tracking-widest opacity-70">
          <span>{isUser ? 'Vos' : 'TutorIA'}</span>
          {message.model_used && !isUser && (
            <span className="rounded border px-1 text-[9px] font-mono normal-case">
              {message.model_used}
            </span>
          )}
          {message._pending && !isUser && (
            <span className="text-[9px] normal-case flex items-center gap-1">
              <Loader2 className="size-2.5 animate-spin" aria-hidden />
              {message._phase === 'tools' ? 'usando herramientas' : 'pensando'}
            </span>
          )}
        </div>
        {hasSteps && (
          <div className="mb-2 rounded-md border bg-background/40 px-2 py-1.5">
            <MessageSteps steps={steps} compact={showStepsCompact} />
          </div>
        )}
        {isUser ? (
          message.content || (message._pending ? '▍' : '')
        ) : message._pending && message.content ? (
          // Mientras streamea: plain text con whitespace preservado y
          // cursor. Sin <Markdown> = sin reflows ni sintaxis markdown
          // incompleta visible (``**pal**`` que aparece como literal
          // hasta que cierra el ``**``). Al llegar ``done``
          // (``_pending=false``) caemos al <Markdown> de abajo que sí
          // parsea negritas/listas/etc. con el texto ya completo.
          <span className="whitespace-pre-wrap break-words">
            {message.content}
            <span className="opacity-50 animate-pulse" aria-hidden>
              ▍
            </span>
          </span>
        ) : message.content ? (
          <Markdown content={stripCitations(message.content)} />
        ) : showPhasePlaceholder ? (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            {message._phase === 'tools' ? 'Llamando herramientas…' : 'Pensando…'}
          </span>
        ) : message._pending ? (
          <span className="opacity-50 animate-pulse" aria-hidden>▍</span>
        ) : null}
        {!isUser && hasSteps && !message._pending && (
          <div className="mt-2 text-[9px] opacity-50">
            {steps.length} {steps.length === 1 ? 'paso' : 'pasos'}
          </div>
        )}
      </div>
    </div>
  )
}
