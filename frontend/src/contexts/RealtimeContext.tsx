import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

interface RealtimeMessage {
  channel: string
  event: string
  payload: Record<string, unknown>
}

interface RealtimeContextValue {
  connected: boolean
  lastMessage: RealtimeMessage | null
}

const RealtimeContext = createContext<RealtimeContextValue | undefined>(undefined)

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<RealtimeMessage | null>(null)

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_WS_URL
    if (!wsUrl) {
      return
    }

    const socket = new WebSocket(wsUrl)

    socket.onopen = () => setConnected(true)
    socket.onclose = () => setConnected(false)
    socket.onerror = () => setConnected(false)
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as RealtimeMessage
        setLastMessage(message)
      } catch {
        // Ignore malformed websocket events.
      }
    }

    return () => {
      socket.close()
    }
  }, [])

  const value = useMemo(() => ({ connected, lastMessage }), [connected, lastMessage])

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
}

export function useRealtime() {
  const context = useContext(RealtimeContext)
  if (!context) {
    throw new Error('useRealtime must be used within RealtimeProvider')
  }
  return context
}
