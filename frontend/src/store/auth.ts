import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { getMe, onApiUnauthorized, setAuthToken, type MeResponse, type User } from '@/lib/api'

type AuthState = {
  token: string | null
  user: User | null
  hydrated: boolean
  setSession: (token: string, user: User) => void
  clearSession: () => void
  refreshMe: () => Promise<void>
  markHydrated: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      hydrated: false,
      setSession: (token, user) => {
        setAuthToken(token)
        set({ token, user })
      },
      clearSession: () => {
        setAuthToken(null)
        set({ token: null, user: null })
      },
      refreshMe: async () => {
        const me: MeResponse = await getMe()
        set({ user: me.user })
      },
      markHydrated: () => set({ hydrated: true }),
    }),
    {
      name: 'tutoria-auth',
      partialize: (s) => ({ token: s.token, user: s.user }),
      onRehydrateStorage: () => (state) => {
        if (state?.token) {
          setAuthToken(state.token)
        }
        state?.markHydrated()
      },
    },
  ),
)

onApiUnauthorized(() => {
  useAuthStore.getState().clearSession()
})
