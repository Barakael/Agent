import { useState, type FormEvent } from 'react'
import AppShell from '../components/layout/AppShell'
import { useAuth } from '../contexts/AuthContext'
import { changePassword } from '../services/authService'

export default function ProfilePage() {
  const { user, updateProfile } = useAuth()
  const [name, setName] = useState(user?.name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [statusMessage, setStatusMessage] = useState('')

  const handleProfileUpdate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await updateProfile({ name, email })
    setStatusMessage('Profile updated successfully.')
  }

  const handlePasswordUpdate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await changePassword({
      current_password: currentPassword,
      password: newPassword,
      password_confirmation: confirmPassword,
    })
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setStatusMessage('Password updated successfully.')
  }

  return (
    <AppShell title="Profile and Security">
      <section className="grid gap-4 xl:grid-cols-2">
        <form onSubmit={handleProfileUpdate} className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Profile</h2>
          <div className="mt-3 space-y-2">
            <input className="form-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" />
            <input className="form-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
            <button type="submit" className="btn-primary">
              Save Profile
            </button>
          </div>
        </form>

        <form onSubmit={handlePasswordUpdate} className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Password</h2>
          <div className="mt-3 space-y-2">
            <input
              className="form-input"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Current password"
            />
            <input className="form-input" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="New password" />
            <input
              className="form-input"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
            />
            <button type="submit" className="btn-secondary">
              Update Password
            </button>
          </div>
        </form>
      </section>
      {statusMessage ? <p className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-600 dark:bg-emerald-500/10">{statusMessage}</p> : null}
    </AppShell>
  )
}
