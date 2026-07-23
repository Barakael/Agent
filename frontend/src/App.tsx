import { BrowserRouter, Route, Routes, Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { RealtimeProvider } from './contexts/RealtimeContext'
import { isMessagingMobile } from './config/messaging'
import LoginPage from './pages/Auth/Login'
import RegisterPage from './pages/Auth/Register'
import DashboardPage from './pages/Dashboard'
import ChatPage from './pages/Chat'
import TasksPage from './pages/Tasks'
import TradingPage from './pages/Trading'
import ReportsPage from './pages/Reports'
import ActivityLogsPage from './pages/ActivityLogs'
import MemoryPage from './pages/Memory'
import PermissionsPage from './pages/Permissions'
import AutomationMonitorPage from './pages/AutomationMonitor'
import NotificationsPage from './pages/Notifications'
import ProfilePage from './pages/Profile'
import SystemStatusPage from './pages/SystemStatus'
import './App.css'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="auth-loading">Loading…</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return children
}

function HomeRedirect() {
  if (isMessagingMobile) {
    return <Navigate to="/chat" replace />
  }
  return (
    <ProtectedRoute>
      <DashboardPage />
    </ProtectedRoute>
  )
}

function MessagingGuard({ children }: { children: ReactNode }) {
  if (isMessagingMobile) {
    return <Navigate to="/chat" replace />
  }
  return <ProtectedRoute>{children}</ProtectedRoute>
}

function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <RealtimeProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={isMessagingMobile ? <Navigate to="/login" replace /> : <RegisterPage />} />
              <Route path="/" element={<HomeRedirect />} />
              <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
              <Route path="/tasks" element={<MessagingGuard><TasksPage /></MessagingGuard>} />
              <Route path="/trading" element={<MessagingGuard><TradingPage /></MessagingGuard>} />
              <Route path="/reports" element={<MessagingGuard><ReportsPage /></MessagingGuard>} />
              <Route path="/activity" element={<MessagingGuard><ActivityLogsPage /></MessagingGuard>} />
              <Route path="/memory" element={<MessagingGuard><MemoryPage /></MessagingGuard>} />
              <Route path="/permissions" element={<MessagingGuard><PermissionsPage /></MessagingGuard>} />
              <Route path="/automation" element={<MessagingGuard><AutomationMonitorPage /></MessagingGuard>} />
              <Route path="/notifications" element={<MessagingGuard><NotificationsPage /></MessagingGuard>} />
              <Route path="/profile" element={<MessagingGuard><ProfilePage /></MessagingGuard>} />
              <Route path="/status" element={<MessagingGuard><SystemStatusPage /></MessagingGuard>} />
              <Route path="*" element={<Navigate to={isMessagingMobile ? '/chat' : '/'} replace />} />
            </Routes>
          </BrowserRouter>
        </RealtimeProvider>
      </ThemeProvider>
    </AuthProvider>
  )
}

export default App
