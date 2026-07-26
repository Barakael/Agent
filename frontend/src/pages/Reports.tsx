import { useEffect, useMemo, useState } from 'react'
import { Activity, FileBarChart2, FileText, Target } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import StatCard from '../components/ui/StatCard'
import SectionCard from '../components/ui/SectionCard'
import EmptyState from '../components/ui/EmptyState'
import {
  fetchActivePlan,
  fetchEveningAiPayload,
  fetchTradingJournal,
  fetchTradingMetrics,
  fetchTradingReviews,
  type DailyPlan,
  type EveningAiPayload,
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

function utcToday(): string {
  return new Date().toISOString().slice(0, 10)
}

function topStrategy(payload: EveningAiPayload | null): string {
  if (!payload) return '—'
  const entries = Object.entries(payload.by_strategy)
  if (entries.length === 0) return '—'
  entries.sort((a, b) => b[1].avg_pnl - a[1].avg_pnl || b[1].trades - a[1].trades)
  return entries[0][0]
}

export default function ReportsPage() {
  const [period, setPeriod] = useState<Period>('7d')
  const [metrics, setMetrics] = useState<TradingMetrics | null>(null)
  const [journal, setJournal] = useState<TradeJournalEntry[]>([])
  const [reviews, setReviews] = useState<TradingReview[]>([])
  const [activePlan, setActivePlan] = useState<DailyPlan | null>(null)
  const [dayAgg, setDayAgg] = useState<EveningAiPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    void load()
  }, [])

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [m, j, planResp, reviewsResp, agg] = await Promise.all([
        fetchTradingMetrics(),
        fetchTradingJournal(100),
        fetchActivePlan().catch(() => ({ data: null })),
        fetchTradingReviews().catch(() => ({ reviews: [], latest_ai_decision: null })),
        fetchEveningAiPayload(utcToday()).catch(() => null),
      ])
      setMetrics(m)
      setJournal(j)
      setActivePlan(planResp.data)
      setReviews(reviewsResp.reviews ?? [])
      setDayAgg(agg)
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
  const summary = dayAgg?.summary
  const strategyRows = Object.entries(dayAgg?.by_strategy ?? {}).sort(
    (a, b) => b[1].trades - a[1].trades,
  )
  const regimeRows = Object.entries(dayAgg?.by_regime ?? {}).sort((a, b) => b[1].trades - a[1].trades)
  const hourRows = Object.entries(dayAgg?.by_hour_utc ?? {}).sort((a, b) => a[0].localeCompare(b[0]))
  const maxHourTrades = Math.max(1, ...hourRows.map(([, b]) => b.trades))

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
            Engine metrics, privacy-safe session analysis, journal, and reviews.
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

      <SectionCard title="Today’s session analysis" icon={Activity} className="mb-4">
        <p className="mb-3 text-xs text-[color:var(--wayda-muted)]">
          Privacy-safe aggregates for {dayAgg?.date ?? utcToday()} (no prices or account details). Top strategy:{' '}
          <span className="font-medium text-[color:var(--wayda-ink)] dark:text-slate-100">{topStrategy(dayAgg)}</span>
        </p>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
          <StatCard label="Closed today" value={summary?.trades_closed ?? (loading ? '…' : 0)} />
          <StatCard
            label="Win rate"
            value={summary != null ? `${summary.win_rate_pct}%` : loading ? '…' : '—'}
            tone="accent"
          />
          <StatCard
            label="Avg PnL / trade"
            value={summary != null ? `$${summary.avg_pnl_per_trade}` : loading ? '…' : '—'}
            tone={summary && summary.avg_pnl_per_trade < 0 ? 'danger' : summary && summary.avg_pnl_per_trade > 0 ? 'success' : 'default'}
          />
          <StatCard label="Skips" value={summary?.skips ?? (loading ? '…' : 0)} helper={`${summary?.risk_rejects ?? 0} risk rejects`} />
          <StatCard
            label="Avg confidence"
            value={summary?.avg_confidence != null ? summary.avg_confidence : loading ? '…' : '—'}
          />
          <StatCard
            label="Avg SL / TP pips"
            value={
              summary?.avg_sl_distance_pips != null || summary?.avg_tp_distance_pips != null
                ? `${summary?.avg_sl_distance_pips ?? '—'} / ${summary?.avg_tp_distance_pips ?? '—'}`
                : loading
                  ? '…'
                  : '—'
            }
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="overflow-x-auto lg:col-span-1">
            <p className="mb-1 text-xs font-medium text-[color:var(--wayda-muted)]">By strategy</p>
            {strategyRows.length === 0 ? (
              <p className="text-xs text-[color:var(--wayda-muted)]">No closed trades today.</p>
            ) : (
              <table className="report-table text-xs">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Trades</th>
                    <th>Win %</th>
                    <th>Avg PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {strategyRows.map(([sid, row]) => (
                    <tr key={sid}>
                      <td>{sid}</td>
                      <td className="font-mono-metric">{row.trades}</td>
                      <td className="font-mono-metric">{row.win_rate_pct}%</td>
                      <td className="font-mono-metric">${row.avg_pnl}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="overflow-x-auto lg:col-span-1">
            <p className="mb-1 text-xs font-medium text-[color:var(--wayda-muted)]">By regime</p>
            {regimeRows.length === 0 ? (
              <p className="text-xs text-[color:var(--wayda-muted)]">No regime data yet.</p>
            ) : (
              <table className="report-table text-xs">
                <thead>
                  <tr>
                    <th>Regime</th>
                    <th>Trades</th>
                    <th>Win %</th>
                    <th>Avg PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {regimeRows.map(([regime, row]) => (
                    <tr key={regime}>
                      <td>{regime}</td>
                      <td className="font-mono-metric">{row.trades}</td>
                      <td className="font-mono-metric">{row.win_rate_pct}%</td>
                      <td className="font-mono-metric">${row.avg_pnl}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="lg:col-span-1">
            <p className="mb-1 text-xs font-medium text-[color:var(--wayda-muted)]">By hour (UTC)</p>
            {hourRows.length === 0 ? (
              <p className="text-xs text-[color:var(--wayda-muted)]">No hourly activity yet.</p>
            ) : (
              <ul className="space-y-2">
                {hourRows.map(([hour, row]) => (
                  <li key={hour} className="text-xs">
                    <div className="mb-0.5 flex justify-between gap-2">
                      <span className="font-mono-metric">{hour}:00</span>
                      <span className="text-[color:var(--wayda-muted)]">
                        {row.trades} · {row.win_rate_pct}%
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-[color:var(--wayda-border)] dark:bg-slate-700">
                      <div
                        className="h-full rounded-full bg-[color:var(--wayda-copper)]"
                        style={{ width: `${Math.max(8, (row.trades / maxHourTrades) * 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </SectionCard>

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
          title="Narrative review"
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
                  <th>Strategy</th>
                  <th>Conf</th>
                  <th>Regime</th>
                  <th>Stake</th>
                  <th>P&L</th>
                  <th>Status</th>
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
                    <td className="text-xs">{t.signal_source ?? '—'}</td>
                    <td className="font-mono-metric">{t.confidence != null ? t.confidence : '—'}</td>
                    <td className="text-xs">{t.market_condition ?? '—'}</td>
                    <td className="font-mono-metric">${t.stake}</td>
                    <td className="font-mono-metric">{t.pnl != null ? `$${t.pnl}` : '—'}</td>
                    <td>
                      <span className={statusPillClass(t.status)}>{t.status}</span>
                    </td>
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
