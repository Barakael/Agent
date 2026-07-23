import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bot, Eye, EyeOff } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setLoading(true)
    try {
      await register(name, email, password, confirmPassword)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="auth-split">
      <aside className="auth-hero">
        <div className="auth-hero-glow" />
        {[2, 3, 4, 5, 6, 7].map((n) => (
          <div key={n} className="auth-hero-ring" style={{ width: `${n * 7}rem`, height: `${n * 7}rem`, opacity: 0.4 - n * 0.04 }} />
        ))}
        <div className="auth-hero-inner fade-in">
          <p className="auth-hero-brand">Wayda</p>
          <div className="auth-hero-rule" />
          <p className="auth-hero-copy">Deploy your private assistant workspace with trading ops and daily automation plans.</p>
        </div>
      </aside>

      <section className="auth-form-pane">
        <div className="auth-form-card">
          <div className="auth-mobile-brand">
            <span className="wayda-brand-mark" style={{ background: 'var(--wayda-teal)' }}>
              <Bot size={16} />
            </span>
            <h1 className="text-2xl font-bold tracking-tight">Create account</h1>
          </div>
          <div className="mb-6 hidden lg:block">
            <h1 className="text-2xl font-bold tracking-tight text-[color:var(--wayda-ink)] dark:text-slate-100">Create your Wayda account</h1>
            <p className="mt-1 text-sm text-[color:var(--wayda-muted)]">One workspace for chat, automations, and demo trading.</p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-3">
            <input className="form-input min-h-[44px]" type="text" required placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
            <input className="form-input min-h-[44px]" type="email" required placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <div className="relative">
              <input
                className="form-input min-h-[44px] pr-11"
                type={showPassword ? 'text' : 'password'}
                required
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-[color:var(--wayda-muted)]"
                onClick={() => setShowPassword(!showPassword)}
                aria-label="Toggle password"
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <input
              className="form-input min-h-[44px]"
              type={showPassword ? 'text' : 'password'}
              required
              placeholder="Confirm password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            {error ? <p className="rounded-lg bg-red-50 p-2 text-sm text-red-600 dark:bg-red-500/10">{error}</p> : null}
            <button type="submit" disabled={loading} className="btn-primary min-h-[44px] w-full">
              {loading ? 'Creating account...' : 'Create account'}
            </button>
          </form>
          <p className="mt-4 text-sm text-[color:var(--wayda-muted)]">
            Already have access?{' '}
            <Link className="font-semibold text-[color:var(--wayda-copper)]" to="/login">
              Sign in
            </Link>
          </p>
        </div>
      </section>
    </main>
  )
}
