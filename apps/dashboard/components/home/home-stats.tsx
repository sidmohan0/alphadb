"use client"

import { mockStrategies } from "@/lib/strategy-data"
import { cn } from "@/lib/utils"

export function HomeStats() {
  const running = mockStrategies.filter((s) => s.status === "running")
  const totalPnL = mockStrategies.reduce((sum, s) => sum + s.todayPnL, 0)
  const avgWinRate = running.length > 0
    ? running.reduce((sum, s) => sum + s.winRate, 0) / running.length
    : 0

  const formatPnL = (value: number) => {
    const sign = value >= 0 ? "+" : ""
    return `${sign}$${value.toFixed(0)}`
  }

  return (
    <div className="flex items-center gap-6 text-sm">
      <div>
        <span className="text-muted-foreground">Active: </span>
        <span className="font-medium text-foreground">{running.length}</span>
      </div>
      <div>
        <span className="text-muted-foreground">Today: </span>
        <span className={cn(
          "font-mono font-medium",
          totalPnL >= 0 ? "text-green-500" : "text-red-500"
        )}>
          {formatPnL(totalPnL)}
        </span>
      </div>
      <div>
        <span className="text-muted-foreground">Avg Win: </span>
        <span className="font-medium text-foreground">
          {(avgWinRate * 100).toFixed(0)}%
        </span>
      </div>
    </div>
  )
}
