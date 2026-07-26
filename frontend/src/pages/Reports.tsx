import { useEffect, useMemo, useState } from 'react'
import { FileBarChart2, FileText, Target } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import StatCard from '../components/ui/StatCard'
import SectionCard from '../components/ui/SectionCard'
import EmptyState from '../components/ui/EmptyState'
import {
  fetchActivePlan,
  fetchTradingJournal,
  fetchTradingMetrics,
  fetchTradingReviews,
  type DailyPlan,
  type TradeJournalEntry,
  type TradingMetrics,
  type TradingReview,
} from '../services/tradingService'

type Period = 'today' | '7d' | 'all'

function startOfToday() {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d
}

function daysAgo(n: number) {
  const d = startOfToday()
  d.setDate(d.getDate() - n)
  return d
}

function parseEntryDate(entry: TradeJournalEntry): Date | null {
  if (!entry.created_at) return null
  const d = new Date(entry.created_at)
  return Number.isNaN(d.getTime()) ? null : d
}

function statusPillClass(status: string) {
  const s = status.toLowerCase()
  if (s.includes('win') || s === 'closed' || s === 'taken_profit') return 'status-pill success'
  if (s.includes('loss') || s === 'stopped' || s === 'failed') return 'status-pill danger'
  if (s.includes('open') || s === 'pending') return 'status-pill warn'
  return 'status-pill'
}

export default function ReportsPage() {
  const [period, setPeriod] = useState<Period>('7d')
  const [metrics, setMetrics] = useState<TradingMetrics | null>(null)
  const [journal, setJournal] = useState<TradeJournalEntry[]>([])
  const [reviews, setReviews] = useState<TradingReview[]>([])
  const [activePlan, setActivePlan] = useState<DailyPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    void load()
  }, [])

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [m, j, planResp, reviewsResp] = await Promise.all([
        fetchTradingMetrics(),
        fetchTradingJournal(100),
        fetchActivePlan().catch(() => ({ data: null })),
        fetchTradingReviews().catch(() => ({ reviews: [], latest_ai_decision: null })),
      ])
      setMetrics(m)
      setJournal(j)
      setActivePlan(planResp.data)
      setReviews(reviewsResp.reviews ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load reports')
    } finally {
      setLoading(false)
    }
  }

  const filteredJournal = useMemo(() => {
    if (period === 'all') return journal
    const cutoff = period === 'today' ? startOfToday() : daysAgo(7)
    return journal.filter((entry) => {
      const d = parseEntryDate(entry)
      if (!d) return true
      return d >= cutoff
    })
  }, [journal, period])

  const filteredReviews = useMemo(() => {
    if (period === 'all') return reviews
    const cutoff = period === 'today' ? startOfToday() : daysAgo(7)
    return reviews.filter((review) => {
      if (!review.date) return true
      const d = new Date(review.date)
      if (Number.isNaN(d.getTime())) return true
      return d >= cutoff
    })
  }, [reviews, period])

  const latestReview = filteredReviews[0] ?? reviews[0] ?? null

  const downloadReview = (review: TradingReview) => {
    const blob = new Blob([review.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = review.file || `review-${review.date || 'latest'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <AppShell title="Trading Reports">
      {error ? (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 fade-in">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-[color:var(--wayda-ink)] dark:text-slate-100">
            Trading reports
          </h1>
          <p className="mt-0.5 text-sm text-[color:var(--wayda-muted)]">
            Journal, reviews, and metrics from the trading engine.
          </p>
        </div>
        <div className="flex gap-1 rounded-lg border border-[color:var(--wayda-border)] p-1 dark:border-slate-700">
          {(
            [
              ['today', 'Today'],
              ['7d', '7d'],
              ['all', 'All'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`period-chip ${period === key ? 'active' : ''}`}
              onClick={() => setPeriod(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <section className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total P&L"
          value={metrics ? `$${metrics.total_pnl}` : loading ? '…' : '—'}
          tone={metrics && metrics.total_pnl < 0 ? 'danger' : metrics && metrics.total_pnl > 0 ? 'success' : 'default'}
        />
        <StatCard label="Win rate" value={metrics ? `${metrics.win_rate}%` : loading ? '…' : '—'} tone="accent" />
        <StatCard label="Trades" value={metrics?.total_trades ?? (loading ? '…' : '—')} helper={`${filteredJournal.length} in period filter`} />
        <StatCard
          label="Max drawdown"
          value={metrics ? `$${metrics.max_drawdown}` : loading ? '…' : '—'}
          tone="danger"
        />
      </section>

      <section className="mb-4 grid gap-4 lg:grid-cols-2">
        <SectionCard title="Active plan" icon={Target}>
          {activePlan ? (
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <dt className="text-[color:var(--wayda-muted)]">Date</dt>
                <dd className="font-medium font-mono-metric">{activePlan.date}</dd>
              </div>
              <div>
                <dt className="text-[color:var(--wayda-muted)]">Mode</dt>
                <dd className="font-medium">
                  {activePlan.trade_mode || 'pattern'} / {activePlan.hold_policy || 'intraday'}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-[color:var(--wayda-muted)]">Strategies</dt>
                <dd className="font-medium">
                  {(activePlan.enabled_strategies || [activePlan.strategy_id]).join(', ')}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-[color:var(--wayda-muted)]">Pairs</dt>
                <dd className="font-medium">{activePlan.pairs.join(', ')}</dd>
              </div>
              <div>
                <dt className="text-[color:var(--wayda-muted)]">Risk / max</dt>
                <dd className="font-medium font-mono-metric">
                  {activePlan.risk_percent}% / ${activePlan.max_stake_usd}
                </dd>
              </div>
              <div>
                <dt className="text-[color:var(--wayda-muted)]">SL / TP</dt>
                <dd className="font-medium font-mono-metric">
                  {activePlan.sl_pips} / {activePlan.tp_pips} pips
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-[color:var(--wayda-muted)]">No active plan for today.</p>
          )}
        </SectionCard>

        <SectionCard
          title="Latest review"
          icon={FileText}
          action={
            latestReview ? (
              <button type="button" className="text-xs font-semibold text-[color:var(--wayda-copper)]" onClick={() => downloadReview(latestReview)}>
                Download
              </button>
            ) : null
          }
        >
          {latestReview ? (
            <>
              <p className="mb-2 text-xs text-[color:var(--wayda-muted)]">
                {latestReview.kind === 'evening' ? 'Evening learning · ' : 'Plan review · '}
                {latestReview.file}
                {latestReview.date ? ` · ${latestReview.date}` : ''}
              </p>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-[color:var(--wayda-border)] bg-white/60 p-2 text-xs dark:border-slate-700 dark:bg-slate-900/50">
                {latestReview.content.slice(0, 2000)}
              </pre>
            </>
          ) : (
            <p className="text-sm text-[color:var(--wayda-muted)]">No review markdown yet.</p>
          )}
        </SectionCard>
      </section>

      <SectionCard title="Trade journal" icon={FileBarChart2} className="mb-4">
        {filteredJournal.length === 0 ? (
          <EmptyState title="No journal entries" description="Trades in this period will appear here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="report-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Symbol</th>
                  <th>Dir</th>
                  <th>Stake</th>
                  <th>P&L</th>
                  <th>Status</th>
                  <th>Mode</th>
                </tr>
              </thead>
              <tbody>
                {filteredJournal.map((t) => (
                  <tr key={t.id}>
                    <td className="font-mono-metric text-xs">
                      {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
                    </td>
                    <td>{t.symbol}</td>
                    <td className="uppercase">{t.direction}</td>
                    <td className="font-mono-metric">${t.stake}</td>
                    <td className="font-mono-metric">{t.pnl != null ? `$${t.pnl}` : '—'}</td>
                    <td>
                      <span className={statusPillClass(t.status)}>{t.status}</span>
                    </td>
                    <td>{t.mode}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {filteredReviews.length > 1 ? (
        <SectionCard title="Review archive" icon={FileText}>
          <ul className="space-y-2">
            {filteredReviews.map((review) => (
              <li
                key={review.file}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[color:var(--wayda-border)] p-3 text-sm dark:border-slate-700"
              >
                <div>
                  <p className="font-medium">{review.file}</p>
                  <p className="text-xs text-[color:var(--wayda-muted)]">{review.date ?? 'undated'}</p>
                </div>
                <button type="button" className="btn-secondary text-xs" onClick={() => downloadReview(review)}>
                  Download .md
                </button>
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
    </AppShell>
  )
}
