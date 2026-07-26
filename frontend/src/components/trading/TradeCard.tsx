import type { TradeJournalEntry } from '../../services/tradingService'

function statusPillClass(status: string) {
  const s = status.toLowerCase()
  if (s.includes('win') || s === 'closed' || s === 'taken_profit') return 'status-pill success'
  if (s.includes('loss') || s === 'stopped' || s === 'failed') return 'status-pill danger'
  if (s.includes('open') || s === 'pending') return 'status-pill warn'
  return 'status-pill'
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const sec = Math.round((Date.now() - d.getTime()) / 1000)
  if (sec < 60) return `${Math.max(0, sec)}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return d.toLocaleDateString()
}

export default function TradeCard({ trade }: { trade: TradeJournalEntry }) {
  const meta = [trade.signal_source, trade.confidence != null ? `conf ${trade.confidence}` : null, trade.market_condition]
    .filter(Boolean)
    .join(' · ')

  return (
    <article className="trade-card rounded-lg border border-[color:var(--wayda-border)] bg-white/70 p-3 dark:border-slate-700 dark:bg-slate-900/40">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[color:var(--wayda-ink)] dark:text-slate-100">
            {trade.symbol}{' '}
            <span className="uppercase text-[color:var(--wayda-muted)]">{trade.direction}</span>
          </p>
          {meta ? <p className="mt-0.5 text-xs text-[color:var(--wayda-muted)]">{meta}</p> : null}
        </div>
        <span className={statusPillClass(trade.status)}>{trade.status}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-2 text-xs">
        <div className="font-mono-metric">
          <span className="text-[color:var(--wayda-muted)]">PnL </span>
          <span
            className={
              trade.pnl != null && trade.pnl < 0
                ? 'text-red-600 dark:text-red-400'
                : trade.pnl != null && trade.pnl > 0
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : ''
            }
          >
            {trade.pnl != null ? `$${trade.pnl}` : '—'}
          </span>
          <span className="ml-2 text-[color:var(--wayda-muted)]">Stake ${trade.stake}</span>
        </div>
        <span className="text-[color:var(--wayda-muted)]">{relativeTime(trade.created_at)}</span>
      </div>
    </article>
  )
}
