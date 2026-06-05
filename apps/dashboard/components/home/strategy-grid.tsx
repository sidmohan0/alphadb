"use client"

import { Strategy } from "@/lib/strategy-data"
import { cn } from "@/lib/utils"
import { Circle, Pause, Square } from "lucide-react"
import Link from "next/link"

interface StrategyCardProps {
  strategy: Strategy
}

export function StrategyCard({ strategy }: StrategyCardProps) {
  const statusColor = {
    running: "text-green-500",
    stopped: "text-muted-foreground",
    paused: "text-amber-500",
  }[strategy.status]

  const statusIcon = {
    running: <Circle className="h-2 w-2 fill-current" />,
    stopped: <Square className="h-2 w-2 fill-current" />,
    paused: <Pause className="h-2 w-2 fill-current" />,
  }[strategy.status]

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
  }

  const formatPrice = (price: number) => {
    return price.toLocaleString("en-US", { maximumFractionDigits: 0 })
  }

  const formatPnL = (value: number) => {
    const sign = value >= 0 ? "+" : ""
    return `${sign}$${value.toFixed(2)}`
  }

  return (
    <Link href={`/strategies/${strategy.id}`}>
      <div className="bg-card border border-border rounded-lg p-4 hover:border-primary/50 transition-colors cursor-pointer">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="font-medium text-sm text-foreground">{strategy.name}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {strategy.market} ${formatPrice(strategy.threshold)}
            </p>
          </div>
          <div className={cn("flex items-center gap-1.5 text-xs", statusColor)}>
            {statusIcon}
            <span className="capitalize">{strategy.status}</span>
          </div>
        </div>

        {strategy.status === "running" && (
          <>
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-2xl font-mono font-semibold text-foreground">
                {formatTime(strategy.nextCycleIn)}
              </span>
              <span className="text-xs text-muted-foreground">
                ${formatPrice(strategy.currentPrice)}
              </span>
            </div>

            <div className="text-xs text-muted-foreground mb-3">
              {strategy.position.side ? (
                <span>
                  <span className="text-foreground font-medium uppercase">
                    {strategy.position.side}
                  </span>{" "}
                  @ {strategy.position.price} ({strategy.position.contracts} contracts)
                </span>
              ) : (
                <span>No position</span>
              )}
            </div>

            <div className="flex items-center justify-between text-xs">
              <span className={cn(
                "font-mono",
                strategy.sessionPnL >= 0 ? "text-green-500" : "text-red-500"
              )}>
                {formatPnL(strategy.sessionPnL)}
              </span>
              <span className="text-muted-foreground">
                {(strategy.winRate * 100).toFixed(0)}% win
              </span>
            </div>
          </>
        )}

        {strategy.status === "paused" && (
          <div className="text-xs text-muted-foreground py-2">
            {strategy.assessment}
          </div>
        )}

        {strategy.status === "stopped" && (
          <div className="text-xs text-muted-foreground py-2">
            Strategy stopped
          </div>
        )}
      </div>
    </Link>
  )
}

interface StrategyGridProps {
  strategies: Strategy[]
}

export function StrategyGrid({ strategies }: StrategyGridProps) {
  const running = strategies.filter((s) => s.status === "running")
  const other = strategies.filter((s) => s.status !== "running")

  return (
    <div className="space-y-6">
      {running.length > 0 && (
        <div>
          <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">
            Active ({running.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {running.map((strategy) => (
              <StrategyCard key={strategy.id} strategy={strategy} />
            ))}
          </div>
        </div>
      )}

      {other.length > 0 && (
        <div>
          <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">
            Inactive ({other.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {other.map((strategy) => (
              <StrategyCard key={strategy.id} strategy={strategy} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
