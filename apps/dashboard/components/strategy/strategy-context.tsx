"use client"

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"

export const LIVE_STRATEGIES = [
  { id: "fair_value_live", label: "Fair-value live" },
  { id: "expensive_yes_live", label: "Expensive YES" },
] as const

export type LiveStrategy = (typeof LIVE_STRATEGIES)[number]["id"]

interface StrategyContextValue {
  selectedStrategy: LiveStrategy
  selectedStrategyLabel: string
  setSelectedStrategy: (strategy: LiveStrategy) => void
  strategyReady: boolean
  strategies: typeof LIVE_STRATEGIES
}

const DEFAULT_STRATEGY: LiveStrategy = "fair_value_live"
const STORAGE_KEY = "alphadb:selected-strategy"

const StrategyContext = createContext<StrategyContextValue | null>(null)

export function StrategyProvider({ children }: { children: ReactNode }) {
  const [selectedStrategy, setSelectedStrategyState] = useState<LiveStrategy>(DEFAULT_STRATEGY)
  const [strategyReady, setStrategyReady] = useState(false)

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (isLiveStrategy(saved)) {
      setSelectedStrategyState(saved)
    }
    setStrategyReady(true)
  }, [])

  const setSelectedStrategy = (strategy: LiveStrategy) => {
    setSelectedStrategyState(strategy)
    setStrategyReady(true)
    window.localStorage.setItem(STORAGE_KEY, strategy)
  }

  const value = useMemo<StrategyContextValue>(() => {
    const option = LIVE_STRATEGIES.find((strategy) => strategy.id === selectedStrategy)
    return {
      selectedStrategy,
      selectedStrategyLabel: option?.label || selectedStrategy,
      setSelectedStrategy,
      strategyReady,
      strategies: LIVE_STRATEGIES,
    }
  }, [selectedStrategy, strategyReady])

  return <StrategyContext.Provider value={value}>{children}</StrategyContext.Provider>
}

export function useSelectedStrategy() {
  const context = useContext(StrategyContext)
  if (!context) {
    throw new Error("useSelectedStrategy must be used inside StrategyProvider")
  }
  return context
}

function isLiveStrategy(value: unknown): value is LiveStrategy {
  return LIVE_STRATEGIES.some((strategy) => strategy.id === value)
}
