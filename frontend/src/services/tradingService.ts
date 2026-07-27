import api from './api'

export type TradingStatus = {
  state: string
  mode: string
  pairs?: string[]
  daily_pnl?: number
  kill_switch_active?: boolean
  balance?: number
  loginid?: string
  is_demo?: boolean
  account_type?: 'demo' | 'live'
  account_error?: string | null
  analysis_armed?: boolean
  preflight?: PreflightSnapshot | null
  sources?: Record<string, string>
  session?: {
    session_open: boolean
    must_force_close: boolean
    seconds_until_close: number
    close_time_utc: string
  }
  active_plan?: DailyPlan | null
  stored_plan?: DailyPlan | null
  not_configured?: boolean
}

export type DailyPlan = {
  date: string
  pairs: string[]
  strategy_id: string
  enabled_strategies?: string[]
  trade_mode?: 'pattern' | 'bias'
  directional_bias?: 'buy' | 'sell' | 'neutral'
  hold_policy?: 'intraday' | 'swing'
  max_hold_days?: number
  sl_pips: number
  tp_pips: number
  risk_percent: number
  max_stake_usd: number
  notes?: string
  source?: string
}

export type TradingReview = {
  file: string
  date: string | null
  content: string
  kind?: 'evening' | 'plan'
}

export type PreflightSnapshot = {
  passed?: boolean
  decision?: string
  run_type?: string
  reasons?: string[]
  sources?: {
    backtest?: Record<string, { passed?: boolean; total_pnl?: number; win_rate?: number }>
    metrics?: TradingMetrics
    upcoming_high_impact?: Array<{ title: string; currency: string; time: string }>
    ai_decision?: AnalysisDecision
  }
}

export type AnalysisDecision = {
  id?: number
  decision: string
  summary?: string
  reasons?: string[]
  risks?: string[]
  source?: string
  created_at?: string
}

export type AnalysisSnapshot = {
  symbol: string
  price: number | null
  regime: string | null
  rsi: number | null
  atr: number | null
  epoch: number | null
  bars: number
  best_strategy: string | null
  confidence: number
  skip_reason: string | null
  signal: string | null
  feed_ok: boolean
  last_tick_age_sec: number | null
  updated_at: string | null
}

export type TradingPosition = {
  contract_id: number
  symbol: string
  contract_type: string
  buy_price: number
  profit: number
  date_start: number
}

export type TradeJournalEntry = {
  id: number
  symbol: string
  direction: string
  entry_price: number
  exit_price: number | null
  stake: number
  stop_loss: number
  take_profit: number
  stop_loss_usd?: number | null
  take_profit_usd?: number | null
  pnl: number | null
  status: string
  mode: string
  reason: string | null
  signal_source?: string | null
  confidence?: number | null
  market_condition?: string | null
  score_breakdown?: Record<string, number> | string | null
  sl_tp_method?: string | null
  created_at: string | null
  closed_at?: string | null
}

export type TradingMetrics = {
  total_trades: number
  win_rate: number
  avg_rr: number
  max_drawdown: number
  sharpe_ratio: number
  total_pnl: number
}

export type EveningAiBucket = {
  trades: number
  win_rate_pct: number
  avg_pnl: number
}

export type EveningAiPayload = {
  date: string
  summary: {
    trades_opened: number
    trades_closed: number
    win_rate_pct: number
    avg_pnl_per_trade: number
    skips: number
    risk_rejects: number
    avg_confidence: number | null
    avg_sl_distance_pips: number | null
    avg_tp_distance_pips: number | null
  }
  by_strategy: Record<string, EveningAiBucket>
  by_regime: Record<string, EveningAiBucket>
  by_hour_utc: Record<string, EveningAiBucket>
}

export async function fetchTradingStatus() {
  const response = await api.get<{ data: TradingStatus }>('/trading/status')
  return response.data.data
}

export async function fetchTradingPositions() {
  const response = await api.get<{ data: TradingPosition[] }>('/trading/positions')
  return response.data.data
}

export async function fetchTradingJournal(limit = 50) {
  const response = await api.get<{ data: TradeJournalEntry[] }>('/trading/journal', {
    params: { limit },
  })
  return response.data.data
}

export async function fetchTradingMetrics() {
  const response = await api.get<{ data: TradingMetrics }>('/trading/metrics')
  return response.data.data
}

export async function fetchPreflightLatest() {
  const response = await api.get<{ data: PreflightSnapshot | null; analysis_armed: boolean }>(
    '/trading/preflight',
  )
  return response.data
}

export async function runPreflight() {
  const response = await api.post<{ data: PreflightSnapshot; analysis_armed: boolean }>(
    '/trading/preflight',
  )
  return response.data
}

export async function fetchAnalysisSources() {
  const response = await api.get<{ data: Record<string, string> }>('/trading/analysis/sources')
  return response.data.data
}

export async function fetchAnalysisSnapshots() {
  const response = await api.get<{ data: AnalysisSnapshot[] }>('/trading/analysis/snapshots')
  return response.data.data ?? []
}

export async function fetchAnalysisDecision() {
  const response = await api.get<{ data: AnalysisDecision | null }>('/trading/analysis-decision')
  return response.data.data
}

export async function pauseTrading() {
  const response = await api.post('/trading/pause')
  return response.data
}

export async function resumeTrading() {
  const response = await api.post('/trading/resume')
  return response.data
}

export async function killTrading() {
  const response = await api.post('/trading/kill')
  return response.data
}

export async function startTradingBot() {
  const response = await api.post('/trading/start')
  return response.data
}

export async function stopTradingBot() {
  const response = await api.post('/trading/stop')
  return response.data
}

export async function placeManualOrder(payload: {
  symbol: string
  direction: 'buy' | 'sell'
  stake: number
  stop_loss: number
  take_profit: number
}) {
  const response = await api.post('/trading/orders', payload)
  return response.data
}

export async function closePosition(contractId: number) {
  const response = await api.post(`/trading/positions/${contractId}/close`)
  return response.data
}

export async function closeAllPositions() {
  const response = await api.post('/trading/positions/close-all')
  return response.data
}

export async function fetchActivePlan() {
  const response = await api.get<{
    data: DailyPlan | null
    stored?: DailyPlan | null
    active_for_today?: boolean
  }>('/trading/plan/active')
  return response.data
}

export async function fetchTradingReviews() {
  const response = await api.get<{
    data: {
      reviews: TradingReview[]
      latest_ai_decision: AnalysisDecision | null
    }
  }>('/trading/reviews')
  return response.data.data
}

export async function fetchEveningAiPayload(day?: string) {
  const response = await api.get<{ data: EveningAiPayload }>('/trading/evening-ai-payload', {
    params: day ? { day } : undefined,
  })
  return response.data.data
}
