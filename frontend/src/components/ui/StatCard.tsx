import type { ReactNode } from 'react'

export default function StatCard({
  label,
  value,
  helper,
  action,
  tone = 'default',
  className = '',
}: {
  label: string
  value: string | number
  helper?: string
  action?: ReactNode
  tone?: 'default' | 'accent' | 'success' | 'danger' | 'muted'
  className?: string
}) {
  const valueTone =
    tone === 'accent'
      ? 'text-[color:var(--wayda-copper)]'
      : tone === 'success'
        ? 'text-emerald-600 dark:text-emerald-400'
        : tone === 'danger'
          ? 'text-red-600 dark:text-red-400'
          : tone === 'muted'
            ? 'text-[color:var(--wayda-muted)]'
            : 'text-[color:var(--wayda-ink)] dark:text-slate-100'

  return (
    <article className={`glass-card fade-in ${className}`}>
      <p className="panel-title">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tracking-tight font-mono-metric ${valueTone}`}>{value}</p>
      {helper ? <p className="mt-1 text-xs text-[color:var(--wayda-muted)] dark:text-slate-400">{helper}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </article>
  )
}
