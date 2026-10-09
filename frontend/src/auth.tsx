import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, login as apiLogin, setUnauthorizedHandler, tokenStore, type User } from './api'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(!!tokenStore.get())

  const logout = useCallback(() => { tokenStore.set(null); setUser(null) }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    if (!tokenStore.get()) return
    api<User>('/auth/me').then(setUser).catch(logout).finally(() => setLoading(false))
  }, [logout])

  const login = useCallback(async (email: string, password: string) => {
    tokenStore.set(await apiLogin(email, password))
    setUser(await api<User>('/auth/me'))
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}
