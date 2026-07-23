import { useCallback, useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import {
  closeAllPositions,
  closePosition,
  fetchActivePlan,
  fetchAnalysisDecision,
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
  type PreflightSnapshot,
  type TradeJournalEntry,
  type TradingMetrics,
  type TradingPosition,
  type TradingReview,
  type TradingStatus,
} from '../services/tradingService'

const PAIRS = ['frxEURUSD', 'frxGBPUSD', 'frxUSDJPY', 'frxAUDUSD']

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
      const [s, p, j, m, ai, planResp, reviewsResp] = await Promise.all([
        fetchTradingStatus(),
        fetchTradingPositions(),
        fetchTradingJournal(),
        fetchTradingMetrics(),
        fetchAnalysisDecision(),
        fetchActivePlan().catch(() => ({ data: null })),
        fetchTradingReviews().catch(() => ({ reviews: [], latest_ai_decision: null })),
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

  const armedColor = analysisArmed ? 'text-emerald-600' : 'text-red-600'
  const preflightDecision = preflight?.decision ?? 'NO-GO'

  return (
    <AppShell title="Trading">
      {error ? (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <section className="panel mb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Analysis Engine (ATAE)
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              No orders execute unless preflight passes and per-trade scenario analysis succeeds.
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={preflightRunning}
            onClick={() => void handleRunPreflight()}
          >
            {preflightRunning ? 'Running…' : 'Run Preflight'}
          </button>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border p-3 dark:border-slate-700">
            <p className="text-xs text-slate-500">Armed</p>
            <p className={`text-lg font-semibold uppercase ${armedColor}`}>
              {analysisArmed ? 'Yes' : 'Blocked'}
            </p>
          </div>
          <div className="rounded-lg border p-3 dark:border-slate-700">
            <p className="text-xs text-slate-500">Preflight</p>
            <p
              className={`text-lg font-semibold uppercase ${
                preflightDecision === 'GO' ? 'text-emerald-600' : 'text-red-600'
              }`}
            >
              {preflightDecision}
            </p>
          </div>
          <div className="rounded-lg border p-3 dark:border-slate-700">
            <p className="text-xs text-slate-500">AI Daily</p>
            <p
              className={`text-lg font-semibold uppercase ${
                aiDecision?.decision === 'GO' ? 'text-emerald-600' : 'text-slate-500'
              }`}
            >
              {aiDecision?.decision ?? '—'}
            </p>
          </div>
          <div className="rounded-lg border p-3 dark:border-slate-700">
            <p className="text-xs text-slate-500">Mode gate</p>
            <p className="text-lg font-semibold">{status?.mode ?? '—'}</p>
          </div>
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
              <span
                key={name}
                className="rounded-full border px-2 py-0.5 text-xs dark:border-slate-700"
              >
                {name}: {state}
              </span>
            ))}
          </div>
        ) : null}

        {preflight?.sources?.backtest ? (
          <div className="mt-3 overflow-x-auto">
            <p className="mb-1 text-xs font-medium text-slate-600 dark:text-slate-400">Backtest</p>
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b dark:border-slate-700">
                  <th className="py-1 pr-3">Pair</th>
                  <th className="py-1 pr-3">Pass</th>
                  <th className="py-1 pr-3">Win rate</th>
                  <th className="py-1">P&L</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(preflight.sources.backtest).map(([pair, bt]) => (
                  <tr key={pair} className="border-b dark:border-slate-800">
                    <td className="py-1 pr-3">{pair}</td>
                    <td className="py-1 pr-3">{bt.passed ? '✓' : '✗'}</td>
                    <td className="py-1 pr-3">{bt.win_rate != null ? `${bt.win_rate}%` : '—'}</td>
                    <td className="py-1">{bt.total_pnl ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {aiDecision?.summary ? (
          <p className="mt-3 text-xs text-slate-600 dark:text-slate-400">{aiDecision.summary}</p>
        ) : null}
      </section>

      <section className="mb-4 grid gap-4 lg:grid-cols-2">
        <div className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Active plan</h2>
          <p className="mt-1 text-xs text-slate-500">
            Daily directions from automation (clamped by the engine).
          </p>
          {activePlan ? (
            <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div>
                <dt className="text-slate-500">Date</dt>
                <dd className="font-medium">{activePlan.date}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Mode</dt>
                <dd className="font-medium">
                  {activePlan.trade_mode || 'pattern'} / {activePlan.hold_policy || 'intraday'}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Strategy</dt>
                <dd className="font-medium">{activePlan.strategy_id}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Bias</dt>
                <dd className="font-medium">{activePlan.directional_bias || 'neutral'}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-slate-500">Enabled strategies</dt>
                <dd className="font-medium">
                  {(activePlan.enabled_strategies || [activePlan.strategy_id]).join(', ')}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-slate-500">Pairs</dt>
                <dd className="font-medium">{activePlan.pairs.join(', ')}</dd>
              </div>
              <div>
                <dt className="text-slate-500">SL / TP</dt>
                <dd className="font-medium">
                  {activePlan.sl_pips} / {activePlan.tp_pips} pips
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Risk / max stake</dt>
                <dd className="font-medium">
                  {activePlan.risk_percent}% / ${activePlan.max_stake_usd}
                </dd>
              </div>
              {activePlan.max_hold_days ? (
                <div>
                  <dt className="text-slate-500">Max hold days</dt>
                  <dd className="font-medium">{activePlan.max_hold_days}</dd>
                </div>
              ) : null}
              <div className="col-span-2">
                <dt className="text-slate-500">Notes</dt>
                <dd className="font-medium whitespace-pre-wrap">{activePlan.notes || '—'}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-slate-500">Source</dt>
                <dd className="font-medium">{activePlan.source || '—'}</dd>
              </div>
            </dl>
          ) : (
            <p className="mt-3 text-xs text-slate-500">No active plan for today — using .env defaults.</p>
          )}
        </div>
        <div className="panel">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Latest review</h2>
          <p className="mt-1 text-xs text-slate-500">Automation / daily analysis notes.</p>
          {latestReview ? (
            <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border bg-slate-50 p-2 text-xs dark:border-slate-700 dark:bg-slate-900">
              {latestReview.content.slice(0, 2000)}
            </pre>
          ) : aiDecision?.summary ? (
            <p className="mt-3 text-xs text-slate-700 dark:text-slate-300">{aiDecision.summary}</p>
          ) : (
            <p className="mt-3 text-xs text-slate-500">No review yet.</p>
          )}
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <article className="panel xl:col-span-1">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Bot Status</h2>
          {loading ? (
            <p className="mt-2 text-sm text-slate-500">Loading…</p>
          ) : (
            <div className="mt-3 space-y-2 text-sm">
              <p>
                State: <span className={`font-semibold uppercase ${stateColor}`}>{status?.state ?? 'unknown'}</span>
              </p>
              <p>
                Account:{' '}
                <span
                  className={`font-semibold uppercase ${
                    status?.is_demo ? 'text-emerald-600' : 'text-red-600'
                  }`}
                >
                  {status?.account_type ?? '—'}
                </span>
                {status?.loginid ? (
                  <span className="ml-1 text-xs text-slate-500">({status.loginid})</span>
                ) : null}
              </p>
              {!status?.is_demo && status?.loginid ? (
                <p className="text-xs font-medium text-red-600">
                  Live account detected — create a demo PAT on developers.deriv.com or bot will block
                  start.
                </p>
              ) : null}
              {status?.account_error ? (
                <p className="text-xs font-medium text-red-600">{status.account_error}</p>
              ) : null}
              <p>Mode: {status?.mode ?? '—'}</p>
              <p>Daily P&L: ${status?.daily_pnl?.toFixed(2) ?? '0.00'}</p>
              <p>Balance: ${status?.balance?.toFixed(2) ?? '—'}</p>
              {status?.session ? (
                <p className="text-xs text-slate-500">
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
        </article>

        <article className="panel xl:col-span-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Manual Order</h2>
          <p className="mt-1 text-xs text-slate-500">Stop loss and take profit are mandatory.</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
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
        </article>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-2">
        <article className="panel">
          <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Open Positions</h2>
          {positions.length === 0 ? (
            <EmptyState title="No open positions" description="Autonomous or manual trades will appear here." />
          ) : (
            <div className="space-y-2">
              {positions.map((pos) => (
                <div key={pos.contract_id} className="flex items-center justify-between rounded-lg border p-3 dark:border-slate-700">
                  <div>
                    <p className="font-medium">{pos.symbol}</p>
                    <p className="text-xs text-slate-500">
                      {pos.contract_type} · P&L: {pos.profit}
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
        </article>

        <article className="panel">
          <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Performance</h2>
          {metrics ? (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
                <p className="text-xs text-slate-500">Win rate</p>
                <p className="text-lg font-semibold">{metrics.win_rate}%</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
                <p className="text-xs text-slate-500">Total P&L</p>
                <p className="text-lg font-semibold">${metrics.total_pnl}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
                <p className="text-xs text-slate-500">Trades</p>
                <p className="text-lg font-semibold">{metrics.total_trades}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
                <p className="text-xs text-slate-500">Max drawdown</p>
                <p className="text-lg font-semibold">${metrics.max_drawdown}</p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">No metrics yet</p>
          )}
        </article>
      </section>

      <section className="panel mt-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Trade Journal</h2>
        {journal.length === 0 ? (
          <EmptyState title="No trades logged" description="Signals and trades are recorded in log_only mode." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b dark:border-slate-700">
                  <th className="py-2 pr-4">Symbol</th>
                  <th className="py-2 pr-4">Dir</th>
                  <th className="py-2 pr-4">Entry</th>
                  <th className="py-2 pr-4">P&L</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2">Mode</th>
                </tr>
              </thead>
              <tbody>
                {journal.map((t) => (
                  <tr key={t.id} className="border-b dark:border-slate-800">
                    <td className="py-2 pr-4">{t.symbol}</td>
                    <td className="py-2 pr-4 uppercase">{t.direction}</td>
                    <td className="py-2 pr-4">{t.entry_price}</td>
                    <td className="py-2 pr-4">{t.pnl ?? '—'}</td>
                    <td className="py-2 pr-4">{t.status}</td>
                    <td className="py-2">{t.mode}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </AppShell>
  )
}
