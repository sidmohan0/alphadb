import type { ActivityEvent } from "@/components/trading/activity-stream"

export interface Strategy {
  id: string
  name: string
  market: string
  threshold: number
  status: "running" | "stopped" | "paused"
  position: {
    side: "above" | "below" | null
    price: number | null
    contracts: number
  }
  confidence: number
  assessment: string
  cycleMinutes: number
  nextCycleIn: number // seconds
  currentPrice: number
  sessionPnL: number
  todayPnL: number
  winRate: number
  recentActivity: ActivityEvent[]
}

export const mockStrategies: Strategy[] = [
  {
    id: "btc-68k",
    name: "BTC Above/Below 68K",
    market: "BTC",
    threshold: 68000,
    status: "running",
    position: { side: "above", price: 0.42, contracts: 150 },
    confidence: 0.71,
    assessment: "Holding — momentum favorable",
    cycleMinutes: 15,
    nextCycleIn: 272,
    currentPrice: 67420,
    sessionPnL: 47.2,
    todayPnL: 312,
    winRate: 0.64,
    recentActivity: [
      { id: "1", timestamp: new Date(Date.now() - 2 * 60000), type: "reasoning", message: "Price moved +0.3% — reassessing" },
      { id: "2", timestamp: new Date(Date.now() - 3 * 60000), type: "reasoning", message: "Holding position — spread unfavorable" },
      { id: "3", timestamp: new Date(Date.now() - 15 * 60000), type: "cycle", message: "CYCLE — Bought ABOVE @ 0.42 x150" },
    ],
  },
  {
    id: "btc-70k",
    name: "BTC Above/Below 70K",
    market: "BTC",
    threshold: 70000,
    status: "running",
    position: { side: "below", price: 0.61, contracts: 200 },
    confidence: 0.83,
    assessment: "Strong conviction — holding",
    cycleMinutes: 15,
    nextCycleIn: 272,
    currentPrice: 67420,
    sessionPnL: 89.5,
    todayPnL: 445,
    winRate: 0.72,
    recentActivity: [
      { id: "1", timestamp: new Date(Date.now() - 5 * 60000), type: "trade", message: "Increased position BELOW @ 0.61 x50" },
      { id: "2", timestamp: new Date(Date.now() - 15 * 60000), type: "cycle", message: "CYCLE — Position maintained" },
    ],
  },
  {
    id: "eth-4k",
    name: "ETH Above/Below 4K",
    market: "ETH",
    threshold: 4000,
    status: "paused",
    position: { side: null, price: null, contracts: 0 },
    confidence: 0,
    assessment: "Paused — awaiting market clarity",
    cycleMinutes: 15,
    nextCycleIn: 0,
    currentPrice: 3842,
    sessionPnL: 0,
    todayPnL: 156,
    winRate: 0.58,
    recentActivity: [
      { id: "1", timestamp: new Date(Date.now() - 30 * 60000), type: "human", message: "PAUSED — Manual pause by operator" },
    ],
  },
]

export interface TradingSettings {
  maxPositionSize: number
  maxDailyLoss: number
  minConfidenceThreshold: number
  defaultCycleMinutes: number
  autoRestart: boolean
  notifications: {
    onTrade: boolean
    onCycle: boolean
    onError: boolean
  }
}

export const mockSettings: TradingSettings = {
  maxPositionSize: 500,
  maxDailyLoss: 200,
  minConfidenceThreshold: 0.5,
  defaultCycleMinutes: 15,
  autoRestart: true,
  notifications: {
    onTrade: true,
    onCycle: false,
    onError: true,
  },
}
