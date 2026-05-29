import type { ReactNode } from 'react'

export default function StatCard({
  label,
  value,
  helper,
  action,
}: {
  label: string
  value: string | number
  helper?: string
  action?: ReactNode
}) {
  return (
    <article className="panel">
      <p className="panel-title">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">{value}</p>
      {helper ? <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{helper}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </article>
  )
}
