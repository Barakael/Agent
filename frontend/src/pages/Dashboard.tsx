import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { Activity, Bell, MessageSquare, TrendingUp, FileBarChart2 } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import StatCard from '../components/ui/StatCard'
import SectionCard from '../components/ui/SectionCard'
import { fetchNotifications, fetchSystemHealth, fetchTasks } from '../services/platformService'
import {
  fetchActivePlan,
  fetchTradingMetrics,
  fetchTradingStatus,
  type DailyPlan,
  type TradingMetrics,
  type TradingStatus,
} from '../services/tradingService'
import type { HealthSnapshot, UserNotification } from '../types/platform'
import { useAuth } from '../contexts/AuthContext'

export default function DashboardPage() {
  const { user } = useAuth()
  const [health, setHealth] = useState<HealthSnapshot | null>(null)
  const [notifications, setNotifications] = useState<UserNotification[]>([])
  const [taskCounts, setTaskCounts] = useState({ pending: 0, running: 0, completed: 0, failed: 0 })
  const [tradingStatus, setTradingStatus] = useState<TradingStatus | null>(null)
  const [metrics, setMetrics] = useState<TradingMetrics | null>(null)
  const [activePlan, setActivePlan] = useState<DailyPlan | null>(null)

  useEffect(() => {
    void loadDashboard()
  }, [])

  const loadDashboard = async () => {
    const [healthSnapshot, notificationResponse, taskResponse, status, tradingMetrics, planResp] =
      await Promise.all([
        fetchSystemHealth(),
        fetchNotifications(),
        fetchTasks(),
        fetchTradingStatus().catch(() => null),
        fetchTradingMetrics().catch(() => null),
        fetchActivePlan().catch(() => ({ data: null })),
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
    setTradingStatus(status)
    setMetrics(tradingMetrics)
    setActivePlan(planResp.data ?? status?.active_plan ?? null)
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

  const greeting = useMemo(() => {
    const hour = new Date().getHours()
    if (hour < 12) return 'Good morning'
    if (hour < 18) return 'Good afternoon'
    return 'Good evening'
  }, [])

  const todayLabel = useMemo(
    () =>
      new Date().toLocaleDateString(undefined, {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
      }),
    [],
  )

  const botState = tradingStatus?.state ?? '—'
  const dailyPnl = tradingStatus?.daily_pnl
  const winRate = metrics?.win_rate
  const analysisArmed = tradingStatus?.analysis_armed

  return (
    <AppShell title="Command Center">
      <header className="mb-5 fade-in">
        <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--wayda-muted)]">{todayLabel}</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-[color:var(--wayda-ink)] dark:text-slate-100">
          {greeting}
          {user?.name ? `, ${user.name.split(' ')[0]}` : ''}
        </h1>
        <p className="mt-1 text-sm text-[color:var(--wayda-muted)]">
          Assistant tasks and demo trading at a glance.
        </p>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Pending tasks" value={taskCounts.pending} helper="Queued for execution" />
        <StatCard
          label="Bot state"
          value={String(botState).toUpperCase()}
          helper={tradingStatus?.mode ? `Mode: ${tradingStatus.mode}` : 'Trading engine'}
          tone={botState === 'running' ? 'success' : botState === 'killed' ? 'danger' : 'accent'}
        />
        <StatCard
          label="Daily P&L"
          value={dailyPnl != null ? `$${dailyPnl.toFixed(2)}` : '—'}
          helper={metrics ? `${metrics.total_trades} journal trades` : 'From status'}
          tone={dailyPnl != null && dailyPnl < 0 ? 'danger' : dailyPnl != null && dailyPnl > 0 ? 'success' : 'default'}
        />
        <StatCard
          label="Win rate"
          value={winRate != null ? `${winRate}%` : '—'}
          helper={
            analysisArmed === true
              ? 'Analysis armed'
              : analysisArmed === false
                ? 'Analysis blocked'
                : 'Trading metrics'
          }
          tone={analysisArmed ? 'success' : 'muted'}
        />
      </section>

      {activePlan ? (
        <p className="mt-3 text-xs text-[color:var(--wayda-muted)] fade-in">
          Active plan {activePlan.date}: {(activePlan.enabled_strategies || [activePlan.strategy_id]).join(', ')} ·{' '}
          {activePlan.pairs.slice(0, 3).join(', ')}
          {activePlan.pairs.length > 3 ? '…' : ''} · max ${activePlan.max_stake_usd}
        </p>
      ) : null}

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <SectionCard
          title="Service status"
          icon={Activity}
          action={
            <Link to="/status" className="text-xs font-semibold text-[color:var(--wayda-copper)]">
              Details
            </Link>
          }
        >
          <div className="grid gap-2 sm:grid-cols-2">
            {serviceStatus.map(([label, status]) => (
              <div key={label} className="rounded-lg border border-[color:var(--wayda-border)] p-3 dark:border-slate-700">
                <p className="text-xs uppercase tracking-wide text-[color:var(--wayda-muted)]">{label}</p>
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
            <Link to="/chat" className="btn-primary inline-flex items-center justify-center gap-2">
              <MessageSquare size={14} /> Chat
            </Link>
            <Link to="/trading" className="btn-secondary inline-flex items-center justify-center gap-2">
              <TrendingUp size={14} /> Trading
            </Link>
            <Link to="/reports" className="btn-secondary inline-flex items-center justify-center gap-2">
              <FileBarChart2 size={14} /> Reports
            </Link>
          </div>
        </SectionCard>

        <SectionCard
          title="Latest notifications"
          icon={Bell}
          action={
            <Link to="/notifications" className="text-xs font-semibold text-[color:var(--wayda-copper)]">
              Open center
            </Link>
          }
        >
          <div className="space-y-2">
            {notifications.length === 0 ? (
              <p className="text-sm text-[color:var(--wayda-muted)]">No recent notifications.</p>
            ) : (
              notifications.map((notification) => (
                <div
                  key={notification.id}
                  className="rounded-lg border border-[color:var(--wayda-border)] p-3 dark:border-slate-700"
                >
                  <p className="text-sm font-semibold text-[color:var(--wayda-ink)] dark:text-slate-100">
                    {notification.title}
                  </p>
                  <p className="mt-1 text-xs text-[color:var(--wayda-muted)]">
                    {notification.body ?? 'No details provided.'}
                  </p>
                </div>
              ))
            )}
          </div>
        </SectionCard>
      </section>
    </AppShell>
  )
}
