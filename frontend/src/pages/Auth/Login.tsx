import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await login(email, password)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="auth-page flex min-h-full items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
      <section className="w-full max-w-md rounded-2xl border bg-white p-6 shadow-panel dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Sign in to Wayda</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Access your private AI operating assistant.</p>
        <form onSubmit={handleSubmit} className="mt-5 space-y-3">
          <input className="form-input" type="email" required placeholder="Email" value={email} onChange={(event) => setEmail(event.target.value)} />
          <input className="form-input" type="password" required placeholder="Password" value={password} onChange={(event) => setPassword(event.target.value)} />
          {error ? <p className="rounded-lg bg-red-50 p-2 text-sm text-red-600 dark:bg-red-500/10">{error}</p> : null}
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
        <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">
          New here?{' '}
          <Link className="font-semibold text-brand-600 dark:text-brand-300" to="/register">
            Create an account
          </Link>
        </p>
      </section>
    </main>
  )
}
