import api from './api'

export type TradingStatus = {
  state: string
  mode: string
  pairs?: string[]
  daily_pnl?: number
  kill_switch_active?: boolean
  balance?: number
  session?: {
    session_open: boolean
    must_force_close: boolean
    seconds_until_close: number
    close_time_utc: string
  }
  not_configured?: boolean
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
  pnl: number | null
  status: string
  mode: string
  reason: string | null
  created_at: string | null
}

export type TradingMetrics = {
  total_trades: number
  win_rate: number
  avg_rr: number
  max_drawdown: number
  sharpe_ratio: number
  total_pnl: number
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
