import { useAuth } from '../contexts/AuthContext'
import { Link } from 'react-router-dom'

function DashboardPage() {
  const { user, logout } = useAuth()

  return (
    <main className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h1>Welcome back, {user?.name}</h1>
          <p>Start a conversation or explore the assistant dashboard.</p>
        </div>
        <button type="button" onClick={logout}>
          Sign out
        </button>
      </header>
      <div className="dashboard-actions">
        <Link to="/chat" className="button">Open chat</Link>
      </div>

      <section className="dashboard-content">
        <div className="dashboard-panel">
          <h2>Next steps</h2>
          <ul>
            <li>Create a new AI conversation</li>
            <li>Review your activity history</li>
            <li>Manage access permissions</li>
          </ul>
        </div>

        <div className="dashboard-panel">
          <h2>Agent status</h2>
          <p>Your assistant is ready to help with coding, automation, and productivity.</p>
        </div>
      </section>
    </main>
  )
}

export default DashboardPage
