import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import StatCard from '../components/ui/StatCard'
import { fetchNotifications, fetchSystemHealth, fetchTasks } from '../services/platformService'
import type { HealthSnapshot, UserNotification } from '../types/platform'

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthSnapshot | null>(null)
  const [notifications, setNotifications] = useState<UserNotification[]>([])
  const [taskCounts, setTaskCounts] = useState({ pending: 0, running: 0, completed: 0, failed: 0 })

  useEffect(() => {
    void loadDashboard()
  }, [])

  const loadDashboard = async () => {
    const [healthSnapshot, notificationResponse, taskResponse] = await Promise.all([
      fetchSystemHealth(),
      fetchNotifications(),
      fetchTasks(),
    ])
    setHealth(healthSnapshot)
    setNotifications(notificationResponse.data.slice(0, 5))
    const nextCounts = taskResponse.data.reduce(
      (accumulator, task) => {
        accumulator[task.status] = (accumulator[task.status] ?? 0) + 1
        return accumulator
      },
      { pending: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } as Record<string, number>,
    )
    setTaskCounts({
      pending: nextCounts.pending,
      running: nextCounts.running,
      completed: nextCounts.completed,
      failed: nextCounts.failed,
    })
  }

  const serviceStatus = useMemo(
    () => [
      ['Backend', health?.services.backend.status ?? 'unknown'],
      ['AI Service', health?.services.ai_service.status ?? 'unknown'],
      ['Queue', health?.services.queue.status ?? 'unknown'],
      ['Realtime', health?.services.realtime.status ?? 'unknown'],
    ],
    [health],
  )

  return (
    <AppShell title="Command Center">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Pending Tasks" value={taskCounts.pending} helper="Queued for execution" />
        <StatCard label="Running Tasks" value={taskCounts.running} helper="Currently processing" />
        <StatCard label="Completed Tasks" value={taskCounts.completed} helper="Finished successfully" />
        <StatCard label="Failed Tasks" value={taskCounts.failed} helper="Require attention" />
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <article className="panel">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Service Status</h2>
            <Link to="/status" className="text-xs font-semibold text-brand-600 dark:text-brand-300">
              View details
            </Link>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {serviceStatus.map(([label, status]) => (
              <div key={label} className="rounded-lg border p-3 dark:border-slate-700">
                <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
                <p
                  className={`mt-1 text-sm font-semibold ${
                    status === 'ok' || status === 'configured'
                      ? 'text-emerald-600 dark:text-emerald-300'
                      : 'text-amber-600 dark:text-amber-300'
                  }`}
                >
                  {status}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <Link to="/chat" className="btn-primary">
              Open Chat
            </Link>
            <Link to="/tasks" className="btn-secondary">
              Manage Tasks
            </Link>
            <Link to="/permissions" className="btn-secondary">
              Review Permissions
            </Link>
          </div>
        </article>

        <article className="panel">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Latest Notifications</h2>
            <Link to="/notifications" className="text-xs font-semibold text-brand-600 dark:text-brand-300">
              Open center
            </Link>
          </div>
          <div className="space-y-2">
            {notifications.length === 0 ? (
              <p className="text-sm text-slate-500">No recent notifications.</p>
            ) : (
              notifications.map((notification) => (
                <div key={notification.id} className="rounded-lg border p-3 dark:border-slate-700">
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{notification.title}</p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{notification.body ?? 'No details provided.'}</p>
                </div>
              ))
            )}
          </div>
        </article>
      </section>
    </AppShell>
  )
}
