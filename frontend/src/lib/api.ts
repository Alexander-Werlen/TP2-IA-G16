import axios, { type AxiosInstance } from 'axios'

export type User = {
  id: number
  email: string
  name: string
  created_at: string
}

export type UserProfile = {
  user_id: number
  career: string
  current_year: number | null
  preferences: Record<string, unknown>
}

export type MeResponse = { user: User; profile: UserProfile }

export type Materia = { id: number; code: string; name: string }
export type YearNode = { year: number; name: string; materias: Materia[] }
export type Carrera = { career: string; years: YearNode[] }

export type Modulo = {
  id: number
  materia_id: number
  materia_name: string
  materia_code: string
  materia_year: number
  name: string
  created_at: string
}
export type ModuloList = { items: Modulo[] }

export type Chat = {
  id: number
  modulo_id: number
  title: string
  created_at: string
}
export type ChatList = { items: Chat[] }

export type Message = {
  id: number
  chat_id: number
  role: 'user' | 'assistant' | string
  content: string
  model_used: string | null
  created_at: string
}
export type MessageList = { items: Message[] }
export type MessageSendResult = {
  user_message: Message
  assistant_message: Message
}

const API_BASE = '/api'

// Se inicializa con un token null y el store de auth lo actualiza al arrancar.
let authToken: string | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (authToken) {
    config.headers = config.headers ?? {}
    ;(config.headers as Record<string, string>).Authorization = `Bearer ${authToken}`
  }
  return config
})

let onUnauthorized: (() => void) | null = null
export function onApiUnauthorized(cb: () => void) {
  onUnauthorized = cb
}

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      if (onUnauthorized) onUnauthorized()
    }
    return Promise.reject(error)
  },
)

export async function getHealth(): Promise<{ status: string } | null> {
  try {
    const res = await api.get<{ status: string }>('/health')
    return res.data
  } catch {
    return null
  }
}

export type RegisterPayload = { email: string; password: string; name: string }
export type LoginPayload = { email: string; password: string }

export async function register(payload: RegisterPayload): Promise<User> {
  const res = await api.post<User>('/auth/register', payload)
  return res.data
}

export async function login(payload: LoginPayload): Promise<{ access_token: string }> {
  const res = await api.post<{ access_token: string }>('/auth/login', payload)
  return res.data
}

export async function getMe(): Promise<MeResponse> {
  const res = await api.get<MeResponse>('/auth/me')
  return res.data
}

export async function getCarrera(): Promise<Carrera> {
  const res = await api.get<Carrera>('/carrera')
  return res.data
}

// ── Módulos ────────────────────────────────────────────────────────
export type CreateModuloPayload = { materia_id: number; name: string }

export async function listModulos(materiaId?: number): Promise<ModuloList> {
  const res = await api.get<ModuloList>('/modulos', {
    params: materiaId ? { materia_id: materiaId } : undefined,
  })
  return res.data
}

export async function createModulo(payload: CreateModuloPayload): Promise<Modulo> {
  const res = await api.post<Modulo>('/modulos', payload)
  return res.data
}

export async function deleteModulo(moduloId: number): Promise<void> {
  await api.delete(`/modulos/${moduloId}`)
}

// ── Chats ──────────────────────────────────────────────────────────
export type CreateChatPayload = { modulo_id: number; title: string }

export async function listChats(moduloId?: number): Promise<ChatList> {
  const res = await api.get<ChatList>('/chats', {
    params: moduloId ? { modulo_id: moduloId } : undefined,
  })
  return res.data
}

export async function createChat(payload: CreateChatPayload): Promise<Chat> {
  const res = await api.post<Chat>('/chats', payload)
  return res.data
}

export async function deleteChat(chatId: number): Promise<void> {
  await api.delete(`/chats/${chatId}`)
}

// ── Mensajes ───────────────────────────────────────────────────────
export type SendMessagePayload = { content: string; model?: string }

export async function listMessages(chatId: number): Promise<MessageList> {
  const res = await api.get<MessageList>(`/chats/${chatId}/messages`)
  return res.data
}

export async function sendMessage(
  chatId: number,
  payload: SendMessagePayload,
): Promise<MessageSendResult> {
  const res = await api.post<MessageSendResult>(
    `/chats/${chatId}/messages`,
    payload,
  )
  return res.data
}

// ── Documents (Fase 4) ────────────────────────────────────
export type DocumentStatus = 'processing' | 'ready' | 'error' | string

export type Document = {
  id: number
  modulo_id: number
  materia_id: number
  filename: string
  mime: string
  size: number
  summary: string | null
  summary_model: string | null
  status: DocumentStatus
  error_message: string | null
  created_at: string
}

export type DocumentList = { items: Document[] }

export type DocumentStatusSnapshot = {
  id: number
  status: DocumentStatus
  summary: string | null
  error_message: string | null
}

export async function listDocuments(moduloId: number): Promise<DocumentList> {
  const res = await api.get<DocumentList>(`/modulos/${moduloId}/documents`)
  return res.data
}

export async function getDocument(documentId: number): Promise<Document> {
  const res = await api.get<Document>(`/documents/${documentId}`)
  return res.data
}

export async function getDocumentStatus(
  documentId: number,
): Promise<DocumentStatusSnapshot> {
  const res = await api.get<DocumentStatusSnapshot>(
    `/documents/${documentId}/status`,
  )
  return res.data
}

export type UploadProgress = (percent: number) => void

/**
 * Sube un archivo al módulo indicado. Devuelve una `Promise<Document>` con el
 * estado inicial (siempre `processing`). Usa `fetch` (no axios) para poder
 * exponer el progreso de subida vía `onProgress`.
 */
export async function uploadDocument(
  moduloId: number,
  file: File,
  onProgress?: UploadProgress,
): Promise<Document> {
  const form = new FormData()
  form.append('file', file, file.name)

  return new Promise<Document>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/modulos/${moduloId}/documents`, true)
    if (authToken) {
      xhr.setRequestHeader('Authorization', `Bearer ${authToken}`)
    }
    xhr.responseType = 'json'
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && onProgress) {
        const pct = Math.round((ev.loaded / ev.total) * 100)
        onProgress(pct)
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as Document)
      } else {
        const body = xhr.response as { detail?: string } | null
        const message = body?.detail ?? `HTTP ${xhr.status}`
        const err = new Error(message)
        ;(err as Error & { status?: number }).status = xhr.status
        reject(err)
      }
    }
    xhr.onerror = () => {
      reject(new Error('Error de red al subir el archivo'))
    }
    xhr.onabort = () => {
      reject(new Error('Subida cancelada'))
    }
    xhr.send(form)
  })
}

export async function deleteDocument(documentId: number): Promise<void> {
  await api.delete(`/documents/${documentId}`)
}

// ── Memory / Events (Fase 6) ──────────────────────────────────
export type EventItem = {
  id: number
  user_id: number
  materia_id: number | null
  materia_name: string | null
  type: string
  date: string
  description: string
  created_at: string
}

export type EventList = { items: EventItem[] }

export type MemoryResponse = {
  user_id: number
  name: string
  email: string
  career: string
  current_year: number | null
  preferences: Record<string, unknown>
  recent_events: EventItem[]
  upcoming_events: EventItem[]
}

export async function getMemory(): Promise<MemoryResponse> {
  const res = await api.get<MemoryResponse>('/me/memory')
  return res.data
}

export async function listEvents(from?: string, to?: string): Promise<EventList> {
  const res = await api.get<EventList>('/me/events', {
    params: {
      ...(from ? { from } : {}),
      ...(to ? { to } : {}),
    },
  })
  return res.data
}

// ── Streaming SSE (Fase 3 + Fase 6) ───────────────────────────
export type StreamMeta = {
  user_message_id: number
  assistant_message_id: number
  model: string
}

export type StreamTools = {
  tools: string[]
}

export type StreamPhase = {
  phase: 'thinking' | 'tools' | 'answering' | string
}

export type StreamToolCall = {
  id: string
  name: string
  arguments: Record<string, unknown>
  description: string
  display_args: Record<string, unknown>
}

export type StreamToolResult = {
  tool: string
  ok: boolean
  summary: Record<string, unknown>
  duration_ms: number
  description: string
}

export type StreamLlmCall = {
  iteration: number
  model: string
  messages_count: number
  total_chars: number
}

export type StreamLlmResponse = {
  iteration: number
  model: string
  finish_reason: string
  text_chars: number
  tool_calls_count: number
  duration_ms: number
}

export type StreamDone = {
  model: string
  tokens_in: number | null
  tokens_out: number | null
  latency_ms: number | null
  assistant_message_id: number
  tools?: string[]
}

export type StreamError = {
  message: string
  code: number | null
}

export type StreamEvent =
  | { type: 'meta'; data: StreamMeta }
  | { type: 'token'; data: string }
  | { type: 'tools'; data: StreamTools }
  | { type: 'phase'; data: StreamPhase }
  | { type: 'tool_call'; data: StreamToolCall }
  | { type: 'tool_result'; data: StreamToolResult }
  | { type: 'llm_call'; data: StreamLlmCall }
  | { type: 'llm_response'; data: StreamLlmResponse }
  | { type: 'done'; data: StreamDone }
  | { type: 'error'; data: StreamError }

export type StreamHandlers = {
  onMeta?: (data: StreamMeta) => void
  onToken?: (token: string) => void
  onTools?: (data: StreamTools) => void
  onPhase?: (data: StreamPhase) => void
  onToolCall?: (data: StreamToolCall) => void
  onToolResult?: (data: StreamToolResult) => void
  onLlmCall?: (data: StreamLlmCall) => void
  onLlmResponse?: (data: StreamLlmResponse) => void
  onDone?: (data: StreamDone) => void
  onError?: (data: StreamError) => void
}

/**
 * Llama al endpoint de streaming SSE. Devuelve un AbortController para que el
 * caller pueda cancelar (p. ej. al desmontar el componente).
 *
 * Usa `fetch` (no `axios`) porque axios no expone el body como ReadableStream
 * de forma cómoda. El response siempre debe ser `text/event-stream`.
 */
export function streamMessage(
  chatId: number,
  payload: SendMessagePayload,
  handlers: StreamHandlers,
): AbortController {
  const controller = new AbortController()

  void (async () => {
    try {
      const res = await fetch(`${API_BASE}/chats/${chatId}/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        // Errores 4xx/5xx con cuerpo JSON
        let detail = `HTTP ${res.status}`
        try {
          const body = (await res.json()) as { detail?: string }
          if (body?.detail) detail = body.detail
        } catch {
          /* ignore */
        }
        handlers.onError?.({ message: detail, code: res.status })
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      // El formato SSE separa eventos con "\n\n". Vamos acumulando hasta
      // encontrar un separador, parseamos, y emitimos.
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        let sepIdx: number
        // eslint-disable-next-line no-cond-assign
        while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
          const rawEvent = buffer.slice(0, sepIdx)
          buffer = buffer.slice(sepIdx + 2)
          const parsed = parseSseEvent(rawEvent)
          if (parsed) dispatchEvent(parsed, handlers)
        }
      }

      // Si quedó algo en el buffer sin separador final, intentamos parsearlo.
      if (buffer.trim()) {
        const parsed = parseSseEvent(buffer)
        if (parsed) dispatchEvent(parsed, handlers)
      }
    } catch (err) {
      if (controller.signal.aborted) return
      const message = err instanceof Error ? err.message : String(err)
      handlers.onError?.({ message, code: null })
    }
  })()

  return controller
}

type ParsedSse =
  | { event: 'meta'; dataJson: string }
  | { event: 'token'; dataRaw: string }
  | { event: 'tools'; dataJson: string }
  | { event: 'phase'; dataJson: string }
  | { event: 'tool_call'; dataJson: string }
  | { event: 'tool_result'; dataJson: string }
  | { event: 'llm_call'; dataJson: string }
  | { event: 'llm_response'; dataJson: string }
  | { event: 'done'; dataJson: string }
  | { event: 'error'; dataJson: string }

function parseSseEvent(raw: string): ParsedSse | null {
  let event = ''
  const dataLines: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      // SSE spec (WHATWG): strip at most one leading space — the field
      // separator that follows the colon. Do NOT use trimStart(): the
      // LLM tokenizer may emit tokens that legitimately start with a
      // space (e.g. " A" in " A continuación"), and trimStart would eat
      // it, collapsing words like "¡Claro!Acontinuacióntehago...".
      const value = line.slice('data:'.length)
      dataLines.push(value.startsWith(' ') ? value.slice(1) : value)
    }
  }
  const data = dataLines.join('\n')
  if (event === 'token') return { event: 'token', dataRaw: data }
  if (event === 'meta') return { event: 'meta', dataJson: data }
  if (event === 'tools') return { event: 'tools', dataJson: data }
  if (event === 'phase') return { event: 'phase', dataJson: data }
  if (event === 'tool_call') return { event: 'tool_call', dataJson: data }
  if (event === 'tool_result') return { event: 'tool_result', dataJson: data }
  if (event === 'llm_call') return { event: 'llm_call', dataJson: data }
  if (event === 'llm_response') return { event: 'llm_response', dataJson: data }
  if (event === 'done') return { event: 'done', dataJson: data }
  if (event === 'error') return { event: 'error', dataJson: data }
  return null
}

function dispatchEvent(parsed: ParsedSse, handlers: StreamHandlers): void {
  if (parsed.event === 'token') {
    handlers.onToken?.(parsed.dataRaw)
    return
  }
  try {
    const json = JSON.parse(parsed.dataJson) as never
    if (parsed.event === 'meta') handlers.onMeta?.(json as StreamMeta)
    else if (parsed.event === 'tools') handlers.onTools?.(json as StreamTools)
    else if (parsed.event === 'phase') handlers.onPhase?.(json as StreamPhase)
    else if (parsed.event === 'tool_call') handlers.onToolCall?.(json as StreamToolCall)
    else if (parsed.event === 'tool_result') handlers.onToolResult?.(json as StreamToolResult)
    else if (parsed.event === 'llm_call') handlers.onLlmCall?.(json as StreamLlmCall)
    else if (parsed.event === 'llm_response') handlers.onLlmResponse?.(json as StreamLlmResponse)
    else if (parsed.event === 'done') handlers.onDone?.(json as StreamDone)
    else if (parsed.event === 'error') handlers.onError?.(json as StreamError)
  } catch {
    // payload malformado: lo notificamos como error
    handlers.onError?.({ message: 'SSE payload inválido', code: null })
  }
}
