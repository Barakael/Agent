import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type ThemeMode = 'light' | 'dark'

interface ThemeContextValue {
  theme: ThemeMode
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeMode>('light')

  useEffect(() => {
    const stored = localStorage.getItem('agent_theme')
    const initialTheme = stored === 'dark' ? 'dark' : 'light'
    setTheme(initialTheme)
    document.body.classList.toggle('dark', initialTheme === 'dark')
  }, [])

  const toggleTheme = () => {
    setTheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      localStorage.setItem('agent_theme', next)
      document.body.classList.toggle('dark', next === 'dark')
      return next
    })
  }

  const value = useMemo(() => ({ theme, toggleTheme }), [theme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return context
}
