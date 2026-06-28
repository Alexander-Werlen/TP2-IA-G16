import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import AppShell from '@/components/AppShell'
import ProtectedRoute from '@/components/ProtectedRoute'
import Chat from '@/pages/Chat'
import DashboardPlaceholder from '@/pages/DashboardPlaceholder'
import Documents from '@/pages/Documents'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import { useAuthStore } from '@/store/auth'

function App() {
  const token = useAuthStore((s) => s.token)
  const hydrated = useAuthStore((s) => s.hydrated)
  const clearSession = useAuthStore((s) => s.clearSession)
  const refreshMe = useAuthStore((s) => s.refreshMe)

  useEffect(() => {
    if (!hydrated || !token) return
    let cancelled = false
    refreshMe().catch(() => {
      if (!cancelled) {
        clearSession()
      }
    })
    return () => {
      cancelled = true
    }
  }, [hydrated, token, refreshMe, clearSession])

  if (!hydrated) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <p className="text-sm text-muted-foreground">Cargando…</p>
      </main>
    )
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route index element={<DashboardPlaceholder />} />
            <Route path="chats/:chatId" element={<Chat />} />
            <Route path="modulos/:moduloId/documents" element={<Documents />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to={token ? '/' : '/login'} replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
