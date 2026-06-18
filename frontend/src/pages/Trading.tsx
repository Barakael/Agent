import { useCallback, useEffect, useState } from 'react'
import AppShell from '../components/layout/AppShell'
import EmptyState from '../components/ui/EmptyState'
import {
  closeAllPositions,
  closePosition,
  fetchTradingJournal,
  fetchTradingMetrics,
  fetchTradingPositions,
  fetchTradingStatus,
  killTrading,
  pauseTrading,
  placeManualOrder,
  resumeTrading,
  startTradingBot,
  type TradeJournalEntry,
  type TradingMetrics,
  type TradingPosition,
  type TradingStatus,
} from '../services/tradingService'

const PAIRS = ['frxEURUSD', 'frxGBPUSD', 'frxUSDJPY', 'frxAUDUSD']

export default function TradingPage() {
  const [status, setStatus] = useState<TradingStatus | null>(null)
  const [positions, setPositions] = useState<TradingPosition[]>([])
  const [journal, setJournal] = useState<TradeJournalEntry[]>([])
  const [metrics, setMetrics] = useState<TradingMetrics | null>(null)
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
      const [s, p, j, m] = await Promise.all([
        fetchTradingStatus(),
        fetchTradingPositions(),
        fetchTradingJournal(),
        fetchTradingMetrics(),
      ])
      setStatus(s)
      setPositions(p)
      setJournal(j)
      setMetrics(m)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load trading data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const interval = setInterval(() => void refresh(), 15000)
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

  return (
    <AppShell title="Trading">
      {error ? (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      ) : null}

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
            <button type="button" className="btn-secondary text-xs" onClick={() => void startTradingBot().then(refresh)}>
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
