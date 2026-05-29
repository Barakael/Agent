import { useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import { fetchSystemHealth } from '../services/platformService'
import type { HealthSnapshot } from '../types/platform'

export default function SystemStatusPage() {
  const [health, setHealth] = useState<HealthSnapshot | null>(null)

  const loadHealth = async () => {
    const response = await fetchSystemHealth()
    setHealth(response)
  }

  useEffect(() => {
    void loadHealth()
    const interval = window.setInterval(() => {
      void loadHealth()
    }, 8000)
    return () => window.clearInterval(interval)
  }, [])

  return (
    <AppShell title="System Status">
      <section className="grid gap-4 lg:grid-cols-2">
        <article className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Services</h2>
          <div className="mt-3 space-y-2">
            {health ? (
              Object.entries(health.services).map(([name, details]) => (
                <div key={name} className="rounded-lg border p-3 text-sm dark:border-slate-700">
                  <p className="font-semibold capitalize text-slate-900 dark:text-slate-100">{name.replace('_', ' ')}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{JSON.stringify(details)}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-500">Loading health snapshot...</p>
            )}
          </div>
        </article>

        <article className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Platform Counts</h2>
          {health ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border p-3 dark:border-slate-700">
                <p className="text-xs uppercase text-slate-500">Unread notifications</p>
                <p className="mt-1 text-2xl font-semibold">{health.counts.unread_notifications}</p>
              </div>
              <div className="rounded-lg border p-3 dark:border-slate-700">
                <p className="text-xs uppercase text-slate-500">Pending approvals</p>
                <p className="mt-1 text-2xl font-semibold">{health.counts.pending_approvals}</p>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">Waiting for data...</p>
          )}
        </article>
      </section>
    </AppShell>
  )
}
