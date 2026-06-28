import { ChevronDown, ChevronRight, FileText, MessageSquarePlus, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { Chat, Modulo, YearNode } from '@/lib/api'

type ModuloKey = number
type ChatKey = number

export type CarreraTreeProps = {
  years: YearNode[]
  openYears: Set<number>
  onToggleYear: (year: number) => void
  modulosByMateria: Map<number, Modulo[]>
  openModulos: Set<ModuloKey>
  onToggleModulo: (id: number) => void
  chatsByModulo: Map<number, Chat[]>
  openChats: Set<ChatKey>
  onToggleChat: (id: number) => void
  onAddModulo: (materiaId: number) => void
  onAddChat: (moduloId: number) => void
  onOpenChat: (chatId: number) => void
  onOpenDocuments: (moduloId: number) => void
  onDeleteModulo: (modulo: Modulo) => void
  onDeleteChat: (chat: Chat) => void
  activeChatId: number | null
}

export default function CarreraTree({
  years,
  openYears,
  onToggleYear,
  modulosByMateria,
  openModulos,
  onToggleModulo,
  chatsByModulo,
  openChats,
  onToggleChat,
  onAddModulo,
  onAddChat,
  onOpenChat,
  onOpenDocuments,
  onDeleteModulo,
  onDeleteChat,
  activeChatId,
}: CarreraTreeProps) {
  return (
    <div className="space-y-2">
      {years.map((y) => (
        <div key={y.year} className="rounded-md border">
          <YearHeader
            name={y.name}
            count={y.materias.length}
            open={openYears.has(y.year)}
            onToggle={() => onToggleYear(y.year)}
          />
          {openYears.has(y.year) && (
            <ul className="px-3 pb-2 space-y-1">
              {y.materias.map((m) => {
                const mods = modulosByMateria.get(m.id) ?? []
                return (
                  <li key={m.id} className="text-sm border-t pt-1">
                    <MateriaRow
                      materiaName={m.name}
                      materiaCode={m.code}
                      moduloCount={mods.length}
                      onAddModulo={() => onAddModulo(m.id)}
                    />
                    {mods.length > 0 && (
                      <ul className="pl-3 mt-1 space-y-1">
                        {mods.map((mod) => (
                          <ModuloNode
                            key={mod.id}
                            modulo={mod}
                            chats={chatsByModulo.get(mod.id) ?? []}
                            open={openModulos.has(mod.id)}
                            onToggle={() => onToggleModulo(mod.id)}
                            onAddChat={() => onAddChat(mod.id)}
                            onOpenChat={onOpenChat}
                            onOpenDocuments={() => onOpenDocuments(mod.id)}
                            onDelete={() => onDeleteModulo(mod)}
                            openChats={openChats}
                            onToggleChat={onToggleChat}
                            onDeleteChat={onDeleteChat}
                            activeChatId={activeChatId}
                          />
                        ))}
                      </ul>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}

function YearHeader({
  name,
  count,
  open,
  onToggle,
}: {
  name: string
  count: number
  open: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-accent rounded-md"
      aria-expanded={open}
    >
      <span className="flex items-center gap-2 font-medium text-sm">
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        {name}
      </span>
      <span className="text-[10px] text-muted-foreground">{count}</span>
    </button>
  )
}

function MateriaRow({
  materiaName,
  materiaCode,
  moduloCount,
  onAddModulo,
}: {
  materiaName: string
  materiaCode: string
  moduloCount: number
  onAddModulo: () => void
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="flex items-center gap-1.5 min-w-0">
        <span className="truncate text-sm">{materiaName}</span>
        <code className="text-[10px] text-muted-foreground shrink-0">{materiaCode}</code>
        <span className="text-[10px] text-muted-foreground shrink-0">·{moduloCount}</span>
      </span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onAddModulo}
        aria-label={`Crear módulo en ${materiaName}`}
        className="size-6"
      >
        <Plus className="size-3.5" />
      </Button>
    </div>
  )
}

function ModuloNode({
  modulo,
  chats,
  open,
  onToggle,
  onAddChat,
  onOpenChat,
  onOpenDocuments,
  onDelete,
  openChats,
  onToggleChat,
  onDeleteChat,
  activeChatId,
}: {
  modulo: Modulo
  chats: Chat[]
  open: boolean
  onToggle: () => void
  onAddChat: () => void
  onOpenChat: (chatId: number) => void
  onOpenDocuments: () => void
  onDelete: () => void
  openChats: Set<ChatKey>
  onToggleChat: (id: number) => void
  onDeleteChat: (chat: Chat) => void
  activeChatId: number | null
}) {
  return (
    <li className="rounded border bg-card/40">
      <div className="flex items-center justify-between gap-1 px-1.5 py-1">
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-1 text-left text-xs hover:underline min-w-0"
          aria-expanded={open}
        >
          {open ? <ChevronDown className="size-3 shrink-0" /> : <ChevronRight className="size-3 shrink-0" />}
          <span className="truncate">{modulo.name}</span>
          <span className="text-[10px] text-muted-foreground shrink-0">·{chats.length}</span>
        </button>
        <div className="flex items-center gap-0.5 shrink-0">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onOpenDocuments}
            aria-label={`Ver documentos de ${modulo.name}`}
            className="size-6"
          >
            <FileText className="size-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onAddChat}
            aria-label={`Crear chat en ${modulo.name}`}
            className="size-6"
          >
            <MessageSquarePlus className="size-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onDelete}
            aria-label={`Eliminar módulo ${modulo.name}`}
            className="size-6 text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
      {open && chats.length > 0 && (
        <ul className="px-4 pb-1.5 space-y-0.5">
          {chats.map((c) => (
            <ChatNode
              key={c.id}
              chat={c}
              open={openChats.has(c.id)}
              onToggle={() => onToggleChat(c.id)}
              onOpen={() => onOpenChat(c.id)}
              onDelete={() => onDeleteChat(c)}
              isActive={activeChatId === c.id}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

function ChatNode({
  chat,
  open: _open,
  onToggle: _onToggle,
  onOpen,
  onDelete,
  isActive,
}: {
  chat: Chat
  open: boolean
  onToggle: () => void
  onOpen: () => void
  onDelete: () => void
  isActive: boolean
}) {
  return (
    <li className="group flex items-center justify-between text-xs py-0.5">
      <button
        type="button"
        onClick={onOpen}
        className={`flex-1 min-w-0 text-left truncate px-1.5 py-0.5 rounded ${
          isActive ? 'bg-accent text-accent-foreground font-medium' : 'hover:bg-accent/50'
        }`}
        title={`Abrir chat: ${chat.title}`}
      >
        💬 {chat.title}
      </button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onDelete}
        aria-label={`Eliminar chat ${chat.title}`}
        className="size-5 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
      >
        <Trash2 className="size-3" />
      </Button>
    </li>
  )
}
