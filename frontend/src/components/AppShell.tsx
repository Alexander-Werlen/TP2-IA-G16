import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'

import Sidenav from '@/components/Sidenav'
import { Button } from '@/components/ui/button'

const SIDENAV_WIDTH = 'w-[280px]'

export default function AppShell() {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    setOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  useEffect(() => {
    if (open) {
      const prev = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = prev
      }
    }
  }, [open])

  return (
    <div className="h-screen flex bg-background overflow-hidden">
      <aside
        className={`hidden md:flex ${SIDENAV_WIDTH} shrink-0 border-r bg-card/30 flex-col`}
      >
        <Sidenav />
      </aside>

      {open && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/50"
          onClick={() => setOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={`md:hidden fixed inset-y-0 left-0 z-50 ${SIDENAV_WIDTH} max-w-[85vw] bg-background border-r shadow-lg transform transition-transform duration-200 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        aria-hidden={!open}
      >
        <div className="flex items-center justify-between p-2 border-b md:hidden">
          <span className="text-xs text-muted-foreground px-2">Menú</span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setOpen(false)}
            aria-label="Cerrar menú"
            className="size-8"
          >
            <X className="size-4" />
          </Button>
        </div>
        <Sidenav onNavigate={() => setOpen(false)} />
      </aside>

      <main className="flex-1 min-w-0 flex flex-col">
        <div className="md:hidden sticky top-0 z-30 flex items-center gap-2 px-3 py-2 border-b bg-background/95 backdrop-blur">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setOpen(true)}
            aria-label="Abrir menú"
            className="size-8"
          >
            <Menu className="size-4" />
          </Button>
          <span className="text-xs font-medium text-muted-foreground">TutorIA</span>
        </div>
        <div className="flex-1 min-h-0 flex flex-col">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
