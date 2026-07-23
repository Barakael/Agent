import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bot, Eye, EyeOff } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import { isMessagingMobile } from '../../config/messaging'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await login(email, password)
      navigate(isMessagingMobile ? '/chat' : '/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  if (isMessagingMobile) {
    return (
      <main className="auth-form-pane min-h-full">
        <div className="auth-form-card">
          <div className="mb-6 flex items-center gap-3">
            <span className="wayda-brand-mark" style={{ background: 'var(--wayda-teal)' }}>
              <Bot size={16} />
            </span>
            <div>
              <h1 className="text-xl font-bold text-[color:var(--wayda-ink)] dark:text-slate-100">Wayda Messaging</h1>
              <p className="text-sm text-[color:var(--wayda-muted)]">Voice chat and remote control.</p>
            </div>
          </div>
          <LoginForm
            email={email}
            password={password}
            showPassword={showPassword}
            error={error}
            loading={loading}
            setEmail={setEmail}
            setPassword={setPassword}
            setShowPassword={setShowPassword}
            onSubmit={handleSubmit}
            showRegister={false}
          />
        </div>
      </main>
    )
  }

  return (
    <main className="auth-split">
      <aside className="auth-hero">
        <div className="auth-hero-glow" />
        {[2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
          <div key={n} className="auth-hero-ring" style={{ width: `${n * 7}rem`, height: `${n * 7}rem`, opacity: 0.45 - n * 0.04 }} />
        ))}
        <div className="auth-hero-inner fade-in">
          <p className="auth-hero-brand">Wayda</p>
          <div className="auth-hero-rule" />
          <p className="auth-hero-copy">Your private AI operating assistant — chat, automate, and run demo trading under hard risk clamps.</p>
          <div className="auth-micro-stats">
            <article>
              <strong>Demo</strong>
              <span>Deriv multipliers</span>
            </article>
            <article>
              <strong>Daily</strong>
              <span>Plan automations</span>
            </article>
            <article>
              <strong>Private</strong>
              <span>On your VPS</span>
            </article>
          </div>
        </div>
      </aside>

      <section className="auth-form-pane">
        <div className="auth-form-card">
          <div className="auth-mobile-brand">
            <span className="wayda-brand-mark" style={{ background: 'var(--wayda-teal)' }}>
              <Bot size={16} />
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-[color:var(--wayda-ink)] dark:text-slate-100">Wayda</h1>
            <p className="text-sm text-[color:var(--wayda-muted)]">Sign in to your workspace</p>
          </div>
          <div className="mb-6 hidden lg:block">
            <h1 className="text-2xl font-bold tracking-tight text-[color:var(--wayda-ink)] dark:text-slate-100">Welcome back</h1>
            <p className="mt-1 text-sm text-[color:var(--wayda-muted)]">Sign in to access Command Center, trading, and automations.</p>
          </div>
          <LoginForm
            email={email}
            password={password}
            showPassword={showPassword}
            error={error}
            loading={loading}
            setEmail={setEmail}
            setPassword={setPassword}
            setShowPassword={setShowPassword}
            onSubmit={handleSubmit}
            showRegister
          />
        </div>
      </section>
    </main>
  )
}

function LoginForm({
  email,
  password,
  showPassword,
  error,
  loading,
  setEmail,
  setPassword,
  setShowPassword,
  onSubmit,
  showRegister,
}: {
  email: string
  password: string
  showPassword: boolean
  error: string | null
  loading: boolean
  setEmail: (v: string) => void
  setPassword: (v: string) => void
  setShowPassword: (v: boolean) => void
  onSubmit: (e: FormEvent<HTMLFormElement>) => void
  showRegister: boolean
}) {
  return (
    <>
      <form onSubmit={onSubmit} className="space-y-3">
        <label className="block text-xs font-semibold uppercase tracking-wide text-[color:var(--wayda-muted)]">
          Email
          <input
            className="form-input mt-1.5 min-h-[44px] text-base"
            type="email"
            required
            placeholder="you@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
          />
        </label>
        <label className="block text-xs font-semibold uppercase tracking-wide text-[color:var(--wayda-muted)]">
          Password
          <div className="relative mt-1.5">
            <input
              className="form-input min-h-[44px] pr-11 text-base"
              type={showPassword ? 'text' : 'password'}
              required
              placeholder="••••••••"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-[color:var(--wayda-muted)]"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </label>
        {error ? <p className="rounded-lg bg-red-50 p-2 text-sm text-red-600 dark:bg-red-500/10">{error}</p> : null}
        <button type="submit" disabled={loading} className="btn-primary min-h-[44px] w-full text-base">
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
      {showRegister ? (
        <p className="mt-4 text-sm text-[color:var(--wayda-muted)]">
          New here?{' '}
          <Link className="font-semibold text-[color:var(--wayda-copper)]" to="/register">
            Create an account
          </Link>
        </p>
      ) : null}
    </>
  )
}
