import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LogOut } from 'lucide-react'

import CarreraTree from '@/components/CarreraTree'
import { Button } from '@/components/ui/button'
import NameDialog, { ConfirmDialog } from '@/components/NameDialog'
import { usePersistedSet } from '@/hooks/usePersistedSet'
import {
  createChat,
  createModulo,
  deleteChat,
  deleteModulo,
  getCarrera,
  listChats,
  listModulos,
  type Carrera,
  type Chat,
  type Modulo,
} from '@/lib/api'
import { useAuthStore } from '@/store/auth'

type SidenavProps = {
  onNavigate?: () => void
}

export default function Sidenav({ onNavigate }: SidenavProps) {
  const navigate = useNavigate()
  const params = useParams()
  const user = useAuthStore((s) => s.user)
  const clearSession = useAuthStore((s) => s.clearSession)
  const qc = useQueryClient()

  const activeChatId =
    params.chatId && Number.isFinite(Number(params.chatId))
      ? Number(params.chatId)
      : null

  const carreraQuery = useQuery<Carrera>({
    queryKey: ['carrera'],
    queryFn: getCarrera,
  })
  const modulosQuery = useQuery({
    queryKey: ['modulos'],
    queryFn: () => listModulos(),
  })
  const chatsQuery = useQuery({
    queryKey: ['chats'],
    queryFn: () => listChats(),
  })

  const [openYears, setOpenYears] = usePersistedSet('openYears')
  const [openModulos, setOpenModulos] = usePersistedSet('openModulos')
  const [openChats, setOpenChats] = usePersistedSet('openChats')

  const [newModuloFor, setNewModuloFor] = useState<number | null>(null)
  const [newChatFor, setNewChatFor] = useState<number | null>(null)
  const [moduloToDelete, setModuloToDelete] = useState<Modulo | null>(null)
  const [chatToDelete, setChatToDelete] = useState<Chat | null>(null)

  const createModuloMut = useMutation({
    mutationFn: (vars: { materia_id: number; name: string }) => createModulo(vars),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['modulos'] })
      setNewModuloFor(null)
    },
  })
  const createChatMut = useMutation({
    mutationFn: (vars: { modulo_id: number; title: string }) => createChat(vars),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['chats'] })
      setNewChatFor(null)
      navigate(`/chats/${created.id}`)
      onNavigate?.()
    },
  })
  const deleteModuloMut = useMutation({
    mutationFn: (id: number) => deleteModulo(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['modulos'] })
      void qc.invalidateQueries({ queryKey: ['chats'] })
      setModuloToDelete(null)
    },
  })
  const deleteChatMut = useMutation({
    mutationFn: (id: number) => deleteChat(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['chats'] })
      setChatToDelete(null)
    },
  })

  const modulosByMateria = useMemo(() => {
    const m = new Map<number, Modulo[]>()
    for (const mod of modulosQuery.data?.items ?? []) {
      if (!m.has(mod.materia_id)) m.set(mod.materia_id, [])
      m.get(mod.materia_id)!.push(mod)
    }
    return m
  }, [modulosQuery.data])

  const chatsByModulo = useMemo(() => {
    const m = new Map<number, Chat[]>()
    for (const c of chatsQuery.data?.items ?? []) {
      if (!m.has(c.modulo_id)) m.set(c.modulo_id, [])
      m.get(c.modulo_id)!.push(c)
    }
    return m
  }, [chatsQuery.data])

  function togglePersisted(
    key: number,
    setter: (updater: (prev: Set<number>) => Set<number>) => void,
  ) {
    setter((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function onLogout() {
    clearSession()
    navigate('/login', { replace: true })
  }

  const loading = carreraQuery.isLoading || modulosQuery.isLoading || chatsQuery.isLoading
  const error =
    carreraQuery.error
      ? 'No se pudo cargar la carrera'
      : modulosQuery.error
      ? 'No se pudieron cargar los módulos'
      : chatsQuery.error
      ? 'No se pudieron cargar los chats'
      : null

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b shrink-0">
        <p className="text-[10px] uppercase tracking-widest text-muted-foreground">TutorIA</p>
        <h2 className="text-sm font-semibold truncate">
          Hola, {user?.name ?? 'estudiante'} 👋
        </h2>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onLogout}
          className="mt-2 w-full"
        >
          <LogOut className="size-3.5" />
          Salir
        </Button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {loading && <p className="text-xs text-muted-foreground">Cargando…</p>}
        {error && <p className="text-xs text-destructive">{error}</p>}
        {carreraQuery.data && (
          <>
            <p className="text-[11px] text-muted-foreground px-1">
              {carreraQuery.data.career}
            </p>
            <CarreraTree
              years={carreraQuery.data.years}
              openYears={openYears}
              onToggleYear={(y) => togglePersisted(y, setOpenYears)}
              modulosByMateria={modulosByMateria}
              openModulos={openModulos}
              onToggleModulo={(id) => togglePersisted(id, setOpenModulos)}
              chatsByModulo={chatsByModulo}
              openChats={openChats}
              onToggleChat={(id) => togglePersisted(id, setOpenChats)}
              onAddModulo={(materiaId) => setNewModuloFor(materiaId)}
              onAddChat={(moduloId) => setNewChatFor(moduloId)}
              onOpenChat={(chatId) => {
                navigate(`/chats/${chatId}`)
                onNavigate?.()
              }}
              onOpenDocuments={(moduloId) => {
                navigate(`/modulos/${moduloId}/documents`)
                onNavigate?.()
              }}
              onDeleteModulo={(m) => setModuloToDelete(m)}
              onDeleteChat={(c) => setChatToDelete(c)}
              activeChatId={activeChatId}
            />
          </>
        )}
      </div>

      <NameDialog
        open={newModuloFor !== null}
        title="Nuevo módulo"
        description="Creá un módulo dentro de esta materia (p. ej. Unidad 1, Parcial 2)."
        label="Nombre del módulo"
        placeholder="Unidad 1"
        submitText="Crear módulo"
        onCancel={() => setNewModuloFor(null)}
        onSubmit={(name: string) => {
          createModuloMut.mutate({ materia_id: newModuloFor!, name })
        }}
      />
      <NameDialog
        open={newChatFor !== null}
        title="Nuevo chat"
        description="Cada chat tiene su propio historial dentro de este módulo."
        label="Título del chat"
        placeholder="Dudas sobre agentes"
        submitText="Crear chat"
        onCancel={() => setNewChatFor(null)}
        onSubmit={(title: string) => {
          createChatMut.mutate({ modulo_id: newChatFor!, title })
        }}
      />
      <ConfirmDialog
        open={moduloToDelete !== null}
        title="Eliminar módulo"
        description={
          moduloToDelete ? (
            <>
              ¿Eliminar el módulo <strong>{moduloToDelete.name}</strong>? Se borrarán
              también todos sus chats y mensajes.
            </>
          ) : null
        }
        onCancel={() => setModuloToDelete(null)}
        onConfirm={() => deleteModuloMut.mutateAsync(moduloToDelete!.id)}
      />
      <ConfirmDialog
        open={chatToDelete !== null}
        title="Eliminar chat"
        description={
          chatToDelete ? (
            <>
              ¿Eliminar el chat <strong>{chatToDelete.title}</strong> y todos sus
              mensajes?
            </>
          ) : null
        }
        onCancel={() => setChatToDelete(null)}
        onConfirm={() => deleteChatMut.mutateAsync(chatToDelete!.id)}
      />
    </div>
  )
}
