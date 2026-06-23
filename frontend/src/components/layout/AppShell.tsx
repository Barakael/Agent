import {
  Bell,
  Bot,
  ClipboardList,
  Cog,
  // Gauge,
  History,
  KeyRound,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Shield,
  Sun,
  TrendingUp,
  UserCircle2,
  X,
} from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import { useState, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { isMessagingMobile } from '../../config/messaging'
import { useAuth } from '../../contexts/AuthContext'
import { useTheme } from '../../contexts/ThemeContext'
import { useRealtime } from '../../contexts/RealtimeContext'

const fullNavigation = [
  { to: '/chat', label: 'Chat', icon: MessageSquare },
  { to: '/tasks', label: 'Tasks', icon: ClipboardList },
  { to: '/trading', label: 'Trading', icon: TrendingUp },
  { to: '/activity', label: 'Activity Logs', icon: History },
  { to: '/memory', label: 'Memory', icon: Bot },
  { to: '/permissions', label: 'Permissions', icon: Shield },
  { to: '/automation', label: 'Automation', icon: Cog },
  { to: '/notifications', label: 'Notifications', icon: Bell },
  { to: '/profile', label: 'Profile', icon: UserCircle2 },
  { to: '/status', label: 'System Status', icon: KeyRound },
]

const messagingNavigation = [{ to: '/chat', label: 'Chat', icon: MessageSquare }]

export default function AppShell({
  title,
  children,
  fullHeight = false,
}: {
  title: string
  children: ReactNode
  fullHeight?: boolean
}) {
  const { user, logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const { connected } = useRealtime()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const navigation = isMessagingMobile ? messagingNavigation : fullNavigation
  const homeLink = isMessagingMobile ? '/chat' : '/'

  return (
    <div className={`wayda-shell ${isMessagingMobile ? 'wayda-messaging-mobile' : ''}`}>
      <aside className={`wayda-sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="wayda-sidebar-head">
          <Link to={homeLink} className="wayda-brand" onClick={() => setSidebarOpen(false)}>
            <Bot size={16} />
            <span>{isMessagingMobile ? 'Wayda' : 'Wayda'}</span>
          </Link>
          <button type="button" className="wayda-icon-button lg:hidden" onClick={() => setSidebarOpen(false)} aria-label="Close sidebar">
            <X size={16} />
          </button>
        </div>

        {!isMessagingMobile ? (
          <button type="button" className="wayda-new-chat">
            <MessageSquare size={15} />
            <span>New chat</span>
          </button>
        ) : null}

        <nav className="wayda-nav">
          {navigation.map((item) => (
            <NavItem key={item.to} to={item.to} label={item.label} icon={item.icon} />
          ))}
        </nav>

        <div className="wayda-sidebar-foot">
          <div className="wayda-user">
            <UserCircle2 size={16} />
            <div>
              <p>{user?.name}</p>
              <span>{connected ? 'Realtime on' : 'Realtime off'}</span>
            </div>
          </div>
          <div className="wayda-sidebar-actions">
            <button type="button" className="wayda-icon-button" onClick={toggleTheme} aria-label="Toggle theme">
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button type="button" className="wayda-icon-button" onClick={() => void logout()} aria-label="Logout">
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {sidebarOpen ? <div className="wayda-backdrop lg:hidden" onClick={() => setSidebarOpen(false)} /> : null}

      <div className="wayda-main">
        <header className="wayda-topbar">
          <div className="wayda-topbar-left">
            <button type="button" className="wayda-icon-button lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar">
              <Menu size={16} />
            </button>
            <h1>{title}</h1>
          </div>
          <p className="wayda-topbar-meta">
            {connected ? 'Realtime connected' : 'Realtime offline'} · {user?.email}
          </p>
        </header>
        <main className={`wayda-content ${fullHeight ? 'full-height' : ''}`}>{children}</main>
      </div>
    </div>
  )
}

function NavItem({ to, label, icon: Icon }: { to: string; label: string; icon: LucideIcon }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `wayda-nav-item ${isActive ? 'active' : ''}`
      }
    >
      <Icon size={15} />
      <span>{label}</span>
    </NavLink>
  )
}
