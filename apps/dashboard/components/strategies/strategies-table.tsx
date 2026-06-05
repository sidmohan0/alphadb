"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { apiGet, apiPost } from "@/lib/alphadb-api"
import { Button } from "@/components/ui/button"
import { FileLock2, Plus, RefreshCw } from "lucide-react"

interface StrategyRecord {
  strategy_id: string
  name: string
  brief: string
  spec: Record<string, unknown>
  status: string
  promotion_stage: string
  updated_at: string
}

interface StrategiesResponse {
  strategies: StrategyRecord[]
}

function text(value: unknown, fallback = "--") {
  if (value === null || value === undefined || value === "") return fallback
  return String(value)
}

function shortTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function StrategiesTable() {
  const [strategies, setStrategies] = useState<StrategyRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [snapshotting, setSnapshotting] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<StrategiesResponse>("/strategies")
      setStrategies(data.strategies || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load strategies")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const createSnapshot = async (strategyId: string) => {
    setSnapshotting(strategyId)
    try {
      await apiPost(`/strategies/${strategyId}/snapshots`, { source: "dashboard" })
    } finally {
      setSnapshotting(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-foreground">Saved Strategy Specs</h2>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
          <Link href="/strategies/new">
            <Button size="sm">
              <Plus className="h-4 w-4" />
              New
            </Button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="border border-destructive/40 bg-destructive/10 rounded-lg p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/50 border-b border-border">
              <th className="text-left font-medium text-muted-foreground px-4 py-2">Name</th>
              <th className="text-left font-medium text-muted-foreground px-4 py-2">Template</th>
              <th className="text-left font-medium text-muted-foreground px-4 py-2">Market</th>
              <th className="text-left font-medium text-muted-foreground px-4 py-2">Stage</th>
              <th className="text-left font-medium text-muted-foreground px-4 py-2">Updated</th>
              <th className="text-right font-medium text-muted-foreground px-4 py-2">Snapshot</th>
            </tr>
          </thead>
          <tbody>
            {strategies.length ? strategies.map((strategy) => {
              const market = strategy.spec.market as Record<string, unknown> | undefined
              return (
                <tr key={strategy.strategy_id} className="border-b border-border last:border-0 hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <Link href={`/strategies/${strategy.strategy_id}`} className="font-medium text-foreground hover:underline">
                      {strategy.name}
                    </Link>
                    <div className="mt-1 text-xs text-muted-foreground line-clamp-1">{strategy.brief || strategy.strategy_id}</div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{text(strategy.spec.template)}</td>
                  <td className="px-4 py-3 font-mono text-xs">{text(market?.series)}</td>
                  <td className="px-4 py-3">{text(strategy.promotion_stage || strategy.status)}</td>
                  <td className="px-4 py-3 text-muted-foreground">{shortTime(strategy.updated_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="outline"
                      size="icon-sm"
                      onClick={() => createSnapshot(strategy.strategy_id)}
                      disabled={snapshotting === strategy.strategy_id}
                      title="Create Strategy Spec snapshot"
                    >
                      <FileLock2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              )
            }) : (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                  {loading ? "Loading strategies..." : "No saved Strategy Specs."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
