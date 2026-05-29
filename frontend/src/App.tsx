import { BrowserRouter, Route, Routes, Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { RealtimeProvider } from './contexts/RealtimeContext'
import LoginPage from './pages/Auth/Login'
import RegisterPage from './pages/Auth/Register'
import DashboardPage from './pages/Dashboard'
import ChatPage from './pages/Chat'
import TasksPage from './pages/Tasks'
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

function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <RealtimeProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
              <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
              <Route path="/tasks" element={<ProtectedRoute><TasksPage /></ProtectedRoute>} />
              <Route path="/activity" element={<ProtectedRoute><ActivityLogsPage /></ProtectedRoute>} />
              <Route path="/memory" element={<ProtectedRoute><MemoryPage /></ProtectedRoute>} />
              <Route path="/permissions" element={<ProtectedRoute><PermissionsPage /></ProtectedRoute>} />
              <Route path="/automation" element={<ProtectedRoute><AutomationMonitorPage /></ProtectedRoute>} />
              <Route path="/notifications" element={<ProtectedRoute><NotificationsPage /></ProtectedRoute>} />
              <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />
              <Route path="/status" element={<ProtectedRoute><SystemStatusPage /></ProtectedRoute>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </RealtimeProvider>
      </ThemeProvider>
    </AuthProvider>
  )
}

export default App
