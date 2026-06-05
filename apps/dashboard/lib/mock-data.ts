// Types for the dashboard data layer
export interface Strategy {
  id: string
  name: string
  marketTicker: string
  configVersion: string
  modelVersion: string
  status: 'live' | 'paused' | 'stopped'
  mode: 'gated-live' | 'dry-run' | 'backtest'
}

export interface OperatingState {
  status: 'gated-live' | 'dry-run' | 'paused'
  latestRunId: string
  latestRunTime: string
  decision: 'submitted' | 'filled' | 'skipped' | 'rejected'
  skipReason?: string
}

export interface RiskMetric {
  label: string
  current: string
  limit: string
  usage: number
  status: 'ok' | 'warning' | 'error'
}

export interface Decision {
  time: string
  market: string
  decision: 'submitted' | 'filled' | 'skipped' | 'rejected'
  reason?: string
}

export interface Order {
  id: string
  time: string
  side: 'YES' | 'NO'
  size: string
  status: 'filled' | 'partial' | 'pending' | 'rejected'
  fill: string
}

export interface EvidenceItem {
  name: string
  status: 'pass' | 'fail' | 'pending'
  detail: string
}

export interface DecisionChainStep {
  step: string
  status: 'ok' | 'blocked' | 'skipped'
  detail: string
}

export interface Artifact {
  name: string
  type: 'json' | 'parquet' | 'csv'
}

export interface SystemHealth {
  name: string
  ok: boolean
}

export interface Backtest {
  name: string
  runs: number
  pnl: string
  status: 'pass' | 'fail' | 'pending'
}

export interface MarketInstance {
  ticker: string
  status: 'traded' | 'skipped' | 'ignored'
  action: string
}

export interface PositionsSummary {
  openExposure: string
  realizedPnl: string
  unsettled: string
  todayPnl: string
}

export interface ResearchCandidate {
  title: string
  description: string
  branch: string
  status: 'pending' | 'promoted' | 'rejected'
}

// Mock data
export const mockStrategy: Strategy = {
  id: 'fv_live_20260604T233310Z',
  name: 'fair_value_btc_15m',
  marketTicker: 'KXBTC15M',
  configVersion: 'dashboard_postgres v2',
  modelVersion: 'threshold_volatility_fair_value.v1',
  status: 'live',
  mode: 'gated-live',
}

export const mockOperatingState: OperatingState = {
  status: 'gated-live',
  latestRunId: 'fv_live_20260604T233310Z',
  latestRunTime: '23:33:10',
  decision: 'skipped',
  skipReason: 'market_exposure_cap_reached',
}

export const mockRiskMetrics: RiskMetric[] = [
  { label: 'Max Order', current: '$250', limit: '$500', usage: 50, status: 'ok' },
  { label: 'Market Exposure', current: '$2,450', limit: '$2,500', usage: 98, status: 'warning' },
  { label: 'Ticker Exposure', current: '$1,200', limit: '$1,500', usage: 80, status: 'ok' },
  { label: 'Daily Loss', current: '-$45', limit: '-$200', usage: 22, status: 'ok' },
  { label: 'Min Edge', current: '2.3%', limit: '1.5%', usage: 0, status: 'ok' },
]

export const mockDecisions: Decision[] = [
  { time: '23:33:10', market: 'KXBTC15M', decision: 'skipped', reason: 'cap_reached' },
  { time: '23:32:55', market: 'KXBTC15M', decision: 'skipped', reason: 'no_edge' },
  { time: '23:32:40', market: 'KXBTC15M', decision: 'submitted' },
  { time: '23:32:25', market: 'KXBTC15M', decision: 'filled' },
  { time: '23:32:10', market: 'KXBTC15M', decision: 'skipped', reason: 'risk_skip' },
]

export const mockOrders: Order[] = [
  { id: 'ord_7a3f', time: '23:32:40', side: 'YES', size: '$125', status: 'filled', fill: '$125' },
  { id: 'ord_6b2e', time: '23:31:15', side: 'NO', size: '$100', status: 'filled', fill: '$100' },
  { id: 'ord_5c1d', time: '23:29:50', side: 'YES', size: '$150', status: 'partial', fill: '$75' },
]

export const mockEvidenceItems: EvidenceItem[] = [
  { name: 'Fair-value replay', status: 'pass', detail: '342 decisions, 98.2% match' },
  { name: 'Walk-forward', status: 'pass', detail: '+$1,234 simulated' },
  { name: 'Fee stress', status: 'pass', detail: 'Edge stable at 2x fees' },
  { name: 'Settlement reconciliation', status: 'pending', detail: 'Awaiting final prints' },
]

export const mockDecisionChain: DecisionChainStep[] = [
  { step: 'Market Data', status: 'ok', detail: 'bid 0.42 / ask 0.44' },
  { step: 'Features', status: 'ok', detail: '12 features computed' },
  { step: 'Model Output', status: 'ok', detail: 'fair_value: 0.438' },
  { step: 'Executable Quotes', status: 'ok', detail: 'YES @ 0.42' },
  { step: 'EV Calculation', status: 'ok', detail: 'EV: +$2.34' },
  { step: 'Risk Check', status: 'blocked', detail: 'market_exposure_cap' },
  { step: 'Order Intent', status: 'skipped', detail: '—' },
  { step: 'Execution', status: 'skipped', detail: '—' },
]

export const mockArtifacts: Artifact[] = [
  { name: 'Decision Log', type: 'json' },
  { name: 'Feature Snapshot', type: 'parquet' },
  { name: 'Model Trace', type: 'json' },
  { name: 'Quote History', type: 'csv' },
]

export const mockSystemHealth: SystemHealth[] = [
  { name: 'Postgres', ok: true },
  { name: 'Kalshi REST', ok: true },
  { name: 'Kalshi WS', ok: true },
  { name: 'Coinbase', ok: true },
  { name: 'Artifact Store', ok: true },
  { name: 'Scheduler', ok: true },
]

export const mockBacktests: Backtest[] = [
  { name: 'Fair-value replay', runs: 342, pnl: '+$1,234', status: 'pass' },
  { name: 'Walk-forward', runs: 128, pnl: '+$892', status: 'pass' },
  { name: 'Fee stress (2x)', runs: 342, pnl: '+$456', status: 'pass' },
  { name: 'Settlement reconciliation', runs: 89, pnl: '—', status: 'pending' },
]

export const mockMarketInstances: MarketInstance[] = [
  { ticker: 'KXBTC15M-26JUN04-68500', status: 'traded', action: 'YES $125' },
  { ticker: 'KXBTC15M-26JUN04-69000', status: 'skipped', action: 'no_edge' },
  { ticker: 'KXBTC15M-26JUN04-69500', status: 'skipped', action: 'cap_reached' },
  { ticker: 'KXBTC15M-26JUN04-70000', status: 'ignored', action: 'low_liquidity' },
]

export const mockPositionsSummary: PositionsSummary = {
  openExposure: '$2,450',
  realizedPnl: '+$342',
  unsettled: '$875',
  todayPnl: '+$45',
}

export const mockResearchCandidate: ResearchCandidate = {
  title: 'Coinbase market-structure features',
  description: 'Promotion blocked pending edge verdict. Walk-forward shows +1.8% edge but fee stress test incomplete.',
  branch: 'coinbase-features-v2',
  status: 'pending',
}
