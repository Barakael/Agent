import { useCallback, useEffect, useState } from 'react'
import { Activity, BookOpen, ClipboardList, Crosshair, Gauge, LineChart } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import SectionCard from '../components/ui/SectionCard'
import StatCard from '../components/ui/StatCard'
import {
  closeAllPositions,
  closePosition,
  fetchActivePlan,
  fetchAnalysisDecision,
  fetchEveningAiPayload,
  fetchTradingJournal,
  fetchTradingMetrics,
  fetchTradingPositions,
  fetchTradingReviews,
  fetchTradingStatus,
  killTrading,
  pauseTrading,
  placeManualOrder,
  resumeTrading,
  runPreflight,
  startTradingBot,
  type AnalysisDecision,
  type DailyPlan,
  type EveningAiPayload,
  type PreflightSnapshot,
  type TradeJournalEntry,
  type TradingMetrics,
  type TradingPosition,
  type TradingReview,
  type TradingStatus,
} from '../services/tradingService'

const PAIRS = ['frxEURUSD', 'frxGBPUSD', 'frxUSDJPY', 'frxAUDUSD']

function topStrategyFromAgg(payload: EveningAiPayload | null): string {
  if (!payload) return '—'
  const entries = Object.entries(payload.by_strategy)
  if (entries.length === 0) return '—'
  entries.sort((a, b) => b[1].avg_pnl - a[1].avg_pnl || b[1].trades - a[1].trades)
  return entries[0][0]
}

export default function TradingPage() {
  const [status, setStatus] = useState<TradingStatus | null>(null)
  const [positions, setPositions] = useState<TradingPosition[]>([])
  const [journal, setJournal] = useState<TradeJournalEntry[]>([])
  const [metrics, setMetrics] = useState<TradingMetrics | null>(null)
  const [preflight, setPreflight] = useState<PreflightSnapshot | null>(null)
  const [analysisArmed, setAnalysisArmed] = useState(false)
  const [sources, setSources] = useState<Record<string, string>>({})
  const [aiDecision, setAiDecision] = useState<AnalysisDecision | null>(null)
  const [activePlan, setActivePlan] = useState<DailyPlan | null>(null)
  const [latestReview, setLatestReview] = useState<TradingReview | null>(null)
  const [dayAgg, setDayAgg] = useState<EveningAiPayload | null>(null)
  const [preflightRunning, setPreflightRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [symbol, setSymbol] = useState(PAIRS[0])
  const [direction, setDirection] = useState<'buy' | 'sell'>('buy')
  const [stake, setStake] = useState('10')
  const [stopLoss, setStopLoss] = useState('')
  const [takeProfit, setTakeProfit] = useState('')

  const refresh = useCallback(async () => {
    try {
      setError('')
      const [s, p, j, m, ai, planResp, reviewsResp, agg] = await Promise.all([
        fetchTradingStatus(),
        fetchTradingPositions(),
        fetchTradingJournal(),
        fetchTradingMetrics(),
        fetchAnalysisDecision(),
        fetchActivePlan().catch(() => ({ data: null })),
        fetchTradingReviews().catch(() => ({ reviews: [], latest_ai_decision: null })),
        fetchEveningAiPayload().catch(() => null),
      ])
      setStatus(s)
      setPositions(p)
      setJournal(j)
      setMetrics(m)
      setPreflight(s.preflight ?? null)
      setAnalysisArmed(s.analysis_armed ?? false)
      setSources(s.sources ?? {})
      setAiDecision(ai)
      setActivePlan(planResp.data ?? s.active_plan ?? null)
      setLatestReview(reviewsResp.reviews?.[0] ?? null)
      setDayAgg(agg)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load trading data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const interval = setInterval(() => void refresh(), 30000)
    return () => clearInterval(interval)
  }, [refresh])

  const handleManualOrder = async () => {
    const sl = parseFloat(stopLoss)
    const tp = parseFloat(takeProfit)
    const stakeNum = parseFloat(stake)
    if (!sl || !tp || !stakeNum) {
      setError('Stake, stop loss, and take profit are required')
      return
    }
    await placeManualOrder({
      symbol,
      direction,
      stake: stakeNum,
      stop_loss: sl,
      take_profit: tp,
    })
    await refresh()
  }

  const stateColor =
    status?.state === 'running'
      ? 'text-emerald-600'
      : status?.state === 'paused'
        ? 'text-amber-600'
        : status?.state === 'killed'
          ? 'text-red-600'
          : 'text-slate-500'

  const handleRunPreflight = async () => {
    setPreflightRunning(true)
    try {
      const result = await runPreflight()
      setPreflight(result.data)
      setAnalysisArmed(result.analysis_armed)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preflight failed')
    } finally {
      setPreflightRunning(false)
    }
  }

  const handleStart = async () => {
    try {
      setError('')
      await startTradingBot()
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start bot')
    }
  }

  const preflightDecision = preflight?.decision ?? 'NO-GO'

  return (
    <AppShell title="Trading">
      {error ? (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <SectionCard
        title="Analysis Engine (ATAE)"
        icon={Activity}
        className="mb-4"
        action={
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={preflightRunning}
            onClick={() => void handleRunPreflight()}
          >
            {preflightRunning ? 'Running…' : 'Run Preflight'}
          </button>
        }
      >
        <p className="mb-3 text-xs text-[color:var(--wayda-muted)]">
          No orders execute unless preflight passes and per-trade scenario analysis succeeds.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Armed" value={analysisArmed ? 'Yes' : 'Blocked'} tone={analysisArmed ? 'success' : 'danger'} />
          <StatCard
            label="Preflight"
            value={preflightDecision}
            tone={preflightDecision === 'GO' ? 'success' : 'danger'}
          />
          <StatCard
            label="AI Daily"
            value={aiDecision?.decision ?? '—'}
            tone={aiDecision?.decision === 'GO' ? 'success' : 'muted'}
          />
          <StatCard label="Mode gate" value={status?.mode ?? '—'} />
        </div>

        {!analysisArmed ? (
          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            Trading blocked — run daily preflight or fix failing checks:{' '}
            {(preflight?.reasons ?? []).slice(0, 4).join('; ') || 'no preflight run yet'}
          </p>
        ) : null}

        {Object.keys(sources).length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(sources).map(([name, state]) => (
              <span key={name} className="status-pill">
                {name}: {state}
              </span>
            ))}
          </div>
        ) : null}

        {preflight?.sources?.backtest ? (
          <div className="mt-3 overflow-x-auto">
            <p className="mb-1 text-xs font-medium text-[color:var(--wayda-muted)]">Backtest</p>
            <table className="report-table text-xs">
              <thead>
                <tr>
                  <th>Pair</th>
                  <th>Pass</th>
                  <th>Win rate</th>
                  <th>P&L</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(preflight.sources.backtest).map(([pair, bt]) => (
                  <tr key={pair}>
                    <td>{pair}</td>
                    <td>{bt.passed ? '✓' : '✗'}</td>
                    <td className="font-mono-metric">{bt.win_rate != null ? `${bt.win_rate}%` : '—'}</td>
                    <td className="font-mono-metric">{bt.total_pnl ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {aiDecision?.summary ? (
          <p className="mt-3 text-xs text-[color:var(--wayda-muted)]">{aiDecision.summary}</p>
        ) : null}
      </SectionCard>

      <SectionCard title="Session analysis" icon={Activity} className="mb-4">
        <p className="mb-3 text-xs text-[color:var(--wayda-muted)]">
          Privacy-safe day aggregates from the journal (no OpenAI required).
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <StatCard label="Armed" value={analysisArmed ? 'Yes' : 'No'} tone={analysisArmed ? 'success' : 'danger'} />
          <StatCard
            label="Win rate today"
            value={dayAgg ? `${dayAgg.summary.win_rate_pct}%` : '—'}
            tone="accent"
          />
          <StatCard label="Skips" value={dayAgg?.summary.skips ?? '—'} helper={`${dayAgg?.summary.risk_rejects ?? 0} rejects`} />
          <StatCard label="Closed today" value={dayAgg?.summary.trades_closed ?? '—'} />
          <StatCard label="Top strategy" value={topStrategyFromAgg(dayAgg)} />
        </div>
      </SectionCard>

      <section className="mb-4 grid gap-4 lg:grid-cols-2">
        <SectionCard title="Active plan" icon={ClipboardList}>
          <p className="mb-3 text-xs text-[color:var(--wayda-muted)]">
            Daily directions from automation (clamped by the engine).
          </p>
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
              <div>
                <dt className="text-[color:var(--wayda-muted)]">Strategy</dt>
                <dd className="font-medium">{activePlan.strategy_id}</dd>
              </div>
              <div>
                <dt className="text-[color:var(--wayda-muted)]">Bias</dt>
                <dd className="font-medium">{activePlan.directional_bias || 'neutral'}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-[color:var(--wayda-muted)]">Enabled strategies</dt>
                <dd className="font-medium">
                  {(activePlan.enabled_strategies || [activePlan.strategy_id]).join(', ')}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-[color:var(--wayda-muted)]">Pairs</dt>
                <dd className="font-medium">{activePlan.pairs.join(', ')}</dd>
              </div>
              <div>
                <dt className="text-[color:var(--wayda-muted)]">SL / TP</dt>
                <dd className="font-medium font-mono-metric">
                  {activePlan.sl_pips} / {activePlan.tp_pips} pips
                </dd>
              </div>
              <div>
                <dt className="text-[color:var(--wayda-muted)]">Risk / max stake</dt>
                <dd className="font-medium font-mono-metric">
                  {activePlan.risk_percent}% / ${activePlan.max_stake_usd}
                </dd>
              </div>
              {activePlan.max_hold_days ? (
                <div>
                  <dt className="text-[color:var(--wayda-muted)]">Max hold days</dt>
                  <dd className="font-medium">{activePlan.max_hold_days}</dd>
                </div>
              ) : null}
              <div className="col-span-2">
                <dt className="text-[color:var(--wayda-muted)]">Notes</dt>
                <dd className="font-medium whitespace-pre-wrap">{activePlan.notes || '—'}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-[color:var(--wayda-muted)]">Source</dt>
                <dd className="font-medium">{activePlan.source || '—'}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-xs text-[color:var(--wayda-muted)]">No active plan for today — using .env defaults.</p>
          )}
        </SectionCard>
        <SectionCard title="Latest review" icon={BookOpen}>
          <p className="mb-3 text-xs text-[color:var(--wayda-muted)]">
            Evening learning reviews and daily plan notes (AI does not trade).
          </p>
          {latestReview ? (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-[color:var(--wayda-border)] bg-white/60 p-2 text-xs dark:border-slate-700 dark:bg-slate-900/50">
              {latestReview.kind === 'evening' ? '[Evening] ' : ''}
              {latestReview.content.slice(0, 2000)}
            </pre>
          ) : aiDecision?.summary ? (
            <p className="text-xs text-[color:var(--wayda-muted)]">{aiDecision.summary}</p>
          ) : (
            <p className="text-xs text-[color:var(--wayda-muted)]">No review yet.</p>
          )}
        </SectionCard>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <SectionCard title="Bot status" icon={Gauge} className="xl:col-span-1">
          {loading ? (
            <p className="text-sm text-[color:var(--wayda-muted)]">Loading…</p>
          ) : (
            <div className="space-y-2 text-sm">
              <p>
                State: <span className={`font-semibold uppercase ${stateColor}`}>{status?.state ?? 'unknown'}</span>
              </p>
              <p>
                Account:{' '}
                <span className={`font-semibold uppercase ${status?.is_demo ? 'text-emerald-600' : 'text-red-600'}`}>
                  {status?.account_type ?? '—'}
                </span>
                {status?.loginid ? (
                  <span className="ml-1 font-mono-metric text-xs text-[color:var(--wayda-muted)]">({status.loginid})</span>
                ) : null}
              </p>
              {!status?.is_demo && status?.loginid ? (
                <p className="text-xs font-medium text-red-600">
                  Live account detected — create a demo PAT on developers.deriv.com or bot will block start.
                </p>
              ) : null}
              {status?.account_error ? (
                <p className="text-xs font-medium text-red-600">{status.account_error}</p>
              ) : null}
              <p>Mode: {status?.mode ?? '—'}</p>
              <p className="font-mono-metric">Daily P&L: ${status?.daily_pnl?.toFixed(2) ?? '0.00'}</p>
              <p className="font-mono-metric">Balance: ${status?.balance?.toFixed(2) ?? '—'}</p>
              {status?.session ? (
                <p className="text-xs text-[color:var(--wayda-muted)]">
                  Session {status.session.session_open ? 'open' : 'closed'} · closes {status.session.close_time_utc} UTC
                </p>
              ) : null}
              {status?.kill_switch_active ? (
                <p className="font-semibold text-red-600">Kill switch active</p>
              ) : null}
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn-secondary text-xs" onClick={() => void handleStart()}>
              Start
            </button>
            <button type="button" className="btn-secondary text-xs" onClick={() => void pauseTrading().then(refresh)}>
              Pause
            </button>
            <button type="button" className="btn-secondary text-xs" onClick={() => void resumeTrading().then(refresh)}>
              Resume
            </button>
            <button type="button" className="btn-secondary text-xs" onClick={() => void closeAllPositions().then(refresh)}>
              Close All
            </button>
            <button type="button" className="btn-secondary text-xs text-red-600" onClick={() => void killTrading().then(refresh)}>
              Kill Switch
            </button>
          </div>
        </SectionCard>

        <SectionCard title="Manual order" icon={Crosshair} className="xl:col-span-2">
          <p className="mb-3 text-xs text-[color:var(--wayda-muted)]">Stop loss and take profit are mandatory.</p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <select className="form-input" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {PAIRS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <select className="form-input" value={direction} onChange={(e) => setDirection(e.target.value as 'buy' | 'sell')}>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
            <input className="form-input" placeholder="Stake ($)" value={stake} onChange={(e) => setStake(e.target.value)} />
            <input className="form-input" placeholder="Stop loss (price)" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} />
            <input className="form-input" placeholder="Take profit (price)" value={takeProfit} onChange={(e) => setTakeProfit(e.target.value)} />
            <button type="button" className="btn-primary" onClick={() => void handleManualOrder()}>
              Place Order
            </button>
          </div>
        </SectionCard>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-2">
        <SectionCard title="Open positions" icon={LineChart}>
          {positions.length === 0 ? (
            <EmptyState title="No open positions" description="Autonomous or manual trades will appear here." />
          ) : (
            <div className="space-y-2">
              {positions.map((pos) => (
                <div
                  key={pos.contract_id}
                  className="flex items-center justify-between rounded-lg border border-[color:var(--wayda-border)] p-3 dark:border-slate-700"
                >
                  <div>
                    <p className="font-medium">{pos.symbol}</p>
                    <p className="font-mono-metric text-xs text-[color:var(--wayda-muted)]">
                      {pos.contract_type} · P&L: {pos.profit} · #{pos.contract_id}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn-secondary text-xs"
                    onClick={() => void closePosition(pos.contract_id).then(refresh)}
                  >
                    Close
                  </button>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="Performance" icon={Gauge}>
          {metrics ? (
            <div className="grid grid-cols-2 gap-3">
              <StatCard label="Win rate" value={`${metrics.win_rate}%`} />
              <StatCard label="Total P&L" value={`$${metrics.total_pnl}`} tone={metrics.total_pnl < 0 ? 'danger' : 'success'} />
              <StatCard label="Trades" value={metrics.total_trades} />
              <StatCard label="Max drawdown" value={`$${metrics.max_drawdown}`} tone="danger" />
            </div>
          ) : (
            <p className="text-sm text-[color:var(--wayda-muted)]">No metrics yet</p>
          )}
        </SectionCard>
      </section>

      <SectionCard title="Trade journal" icon={BookOpen} className="mt-4">
        {journal.length === 0 ? (
          <EmptyState title="No trades logged" description="Signals and trades are recorded in log_only mode." />
        ) : (
          <div className="overflow-x-auto">
            <table className="report-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Dir</th>
                  <th>Strategy</th>
                  <th>Conf</th>
                  <th>Regime</th>
                  <th>Entry</th>
                  <th>P&L</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {journal.map((t) => (
                  <tr key={t.id}>
                    <td>{t.symbol}</td>
                    <td className="uppercase">{t.direction}</td>
                    <td className="text-xs">{t.signal_source ?? '—'}</td>
                    <td className="font-mono-metric">{t.confidence != null ? t.confidence : '—'}</td>
                    <td className="text-xs">{t.market_condition ?? '—'}</td>
                    <td className="font-mono-metric">{t.entry_price}</td>
                    <td className="font-mono-metric">{t.pnl ?? '—'}</td>
                    <td>
                      <span className="status-pill">{t.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </AppShell>
  )
}
