"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { AppShell } from "@/components/app-shell"
import { Button } from "@/components/ui/button"
import { apiGet, apiPost } from "@/lib/alphadb-api"
import { ArrowLeft, FileLock2, RefreshCw } from "lucide-react"

interface StrategyRecord {
  strategy_id: string
  name: string
  brief: string
  spec: Record<string, unknown>
  status: string
  promotion_stage: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

interface StrategyResponse {
  strategy: StrategyRecord
}

export default function StrategyDetailPage() {
  const params = useParams()
  const strategyId = String(params.id)
  const [strategy, setStrategy] = useState<StrategyRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<StrategyResponse>(`/strategies/${strategyId}`)
      setStrategy(data.strategy)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load strategy")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [strategyId])

  const createSnapshot = async () => {
    setSnapshot(null)
    const data = await apiPost<{ snapshot: Record<string, unknown> }>(
      `/strategies/${strategyId}/snapshots`,
      { source: "dashboard" }
    )
    setSnapshot(data.snapshot)
  }

  return (
    <AppShell>
      <div className="p-6 space-y-5 max-w-6xl">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link href="/strategies">
              <Button variant="ghost" size="icon-sm">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
            <div>
              <h1 className="text-lg font-semibold">{strategy?.name || "Strategy"}</h1>
              <p className="text-sm text-muted-foreground">{strategyId}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
            <Button variant="outline" size="sm" onClick={createSnapshot} disabled={!strategy}>
              <FileLock2 className="h-4 w-4" />
              Snapshot
            </Button>
          </div>
        </div>

        {error && (
          <div className="border border-destructive/40 bg-destructive/10 rounded-lg p-3 text-sm text-destructive">
            {error}
          </div>
        )}
        {snapshot && (
          <div className="border border-success/40 bg-success/10 rounded-lg p-3 text-sm text-success">
            Snapshot {String(snapshot.snapshot_id)} created.
          </div>
        )}

        {strategy ? (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
            <section className="border border-border rounded-lg bg-card p-4 space-y-3">
              <h2 className="text-sm font-medium">Strategy Brief</h2>
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">{strategy.brief || "No brief saved."}</p>
            </section>
            <section className="border border-border rounded-lg bg-card p-4 space-y-3">
              <h2 className="text-sm font-medium">Status</h2>
              <Value label="Status" value={strategy.status} />
              <Value label="Stage" value={strategy.promotion_stage} />
              <Value label="Updated" value={shortTime(strategy.updated_at)} />
            </section>
            <section className="lg:col-span-2 border border-border rounded-lg bg-card p-4">
              <h2 className="text-sm font-medium mb-3">Strategy Spec JSON</h2>
              <pre className="max-h-[520px] overflow-auto rounded-md bg-background p-3 text-xs text-muted-foreground">
                {JSON.stringify(strategy.spec, null, 2)}
              </pre>
            </section>
          </div>
        ) : (
          <div className="border border-border rounded-lg p-8 text-center text-muted-foreground">
            {loading ? "Loading strategy..." : "Strategy not found."}
          </div>
        )}
      </div>
    </AppShell>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  )
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
