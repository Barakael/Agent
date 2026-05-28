import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import api from '../services/api'
import { login as loginRequest, register as registerRequest } from '../services/authService'

interface User {
  id: number
  name: string
  email: string
}

interface AuthContextValue {
  user: User | null
  token: string | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string, passwordConfirmation: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const storedToken = localStorage.getItem('agent_auth_token')
    const storedUser = localStorage.getItem('agent_user')

    if (storedToken && storedUser) {
      api.defaults.headers.common.Authorization = `Bearer ${storedToken}`
      setToken(storedToken)
      setUser(JSON.parse(storedUser))
    }

    setLoading(false)
  }, [])

  const login = async (email: string, password: string) => {
    const response = await loginRequest(email, password)
    const { token: authToken, user: userData } = response

    localStorage.setItem('agent_auth_token', authToken)
    localStorage.setItem('agent_user', JSON.stringify(userData))
    api.defaults.headers.common.Authorization = `Bearer ${authToken}`
    setToken(authToken)
    setUser(userData)
  }

  const register = async (name: string, email: string, password: string, passwordConfirmation: string) => {
    const response = await registerRequest(name, email, password, passwordConfirmation)
    const { token: authToken, user: userData } = response

    localStorage.setItem('agent_auth_token', authToken)
    localStorage.setItem('agent_user', JSON.stringify(userData))
    api.defaults.headers.common.Authorization = `Bearer ${authToken}`
    setToken(authToken)
    setUser(userData)
  }

  const logout = () => {
    localStorage.removeItem('agent_auth_token')
    localStorage.removeItem('agent_user')
    delete api.defaults.headers.common.Authorization
    setToken(null)
    setUser(null)
  }

  const value = useMemo(
    () => ({ user, token, loading, login, register, logout }),
    [user, token, loading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
