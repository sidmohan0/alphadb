"use client"

import { useEffect, useMemo, useState, type ReactNode } from "react"
import { apiGet } from "@/lib/alphadb-api"
import { Button } from "@/components/ui/button"
import { Activity, RefreshCw, ShieldAlert, Square } from "lucide-react"

interface LivePayload {
  health?: {
    ok: boolean
    environment: string
    generated_at_utc: string
    components: Array<{ name: string; status: string; detail: string }>
  }
  active_config?: Record<string, unknown>
  live_status?: Record<string, unknown>
  recent_runs?: Array<Record<string, unknown>>
}

function text(value: unknown, fallback = "--") {
  if (value === null || value === undefined || value === "") return fallback
  return String(value)
}

function money(value: unknown) {
  const number = Number(value || 0)
  return `$${number.toFixed(2)}`
}

function shortTime(value: unknown) {
  if (!value) return "--"
  const date = new Date(String(value))
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function LiveOperations() {
  const [payload, setPayload] = useState<LivePayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setPayload(await apiGet<LivePayload>("/live"))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load live status")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = window.setInterval(load, 15000)
    return () => window.clearInterval(id)
  }, [])

  const status = payload?.live_status || {}
  const config = payload?.active_config || {}
  const recentRuns = payload?.recent_runs || []
  const attempts = useMemo(() => {
    const raw = status.recent_attempts
    return Array.isArray(raw) ? raw.slice().reverse() : []
  }, [status.recent_attempts])
  const liveOrdersMetric = (() => {
    if (typeof status.live_orders_enabled === "boolean") {
      return status.live_orders_enabled
        ? { value: "Enabled", tone: "good" as const }
        : { value: "Disabled", tone: "warn" as const }
    }
    if (loading) return { value: "Checking", tone: "muted" as const }
    return {
      value: "Unknown",
      tone: "muted" as const,
      detail: error ? "API unavailable" : "No live status",
    }
  })()

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Live Operations</h1>
          <p className="text-sm text-muted-foreground">
            {text(payload?.health?.environment, "environment unknown")} · {shortTime(payload?.health?.generated_at_utc)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
          <Button variant="destructive" size="sm" disabled title="Backend stop skill is not wired yet">
            <Square className="h-4 w-4" />
            Stop
          </Button>
        </div>
      </div>

      {error && (
        <div className="border border-destructive/40 bg-destructive/10 rounded-lg p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Health" value={payload?.health?.ok ? "OK" : "Unknown"} tone={payload?.health?.ok ? "good" : "muted"} />
        <Metric label="Live Orders" value={liveOrdersMetric.value} tone={liveOrdersMetric.tone} detail={liveOrdersMetric.detail} />
        <Metric label="Market" value={text(status.current_market_ticker, "No recent run")} detail={text(status.run_id, "")} />
        <Metric label="Decision" value={text(status.decision_outcome)} detail={text(status.selected_side || status.skip_reason, "")} />
      </section>

      <section className="grid gap-3 lg:grid-cols-[1fr_360px]">
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-medium">Recent Attempts</h2>
          </div>
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">Time</th>
                  <th className="text-left px-4 py-2 font-medium">Market</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th className="text-left px-4 py-2 font-medium">Reason</th>
                  <th className="text-left px-4 py-2 font-medium">Fill</th>
                </tr>
              </thead>
              <tbody>
                {attempts.length ? attempts.map((attempt, index) => (
                  <tr key={index} className="border-t border-border">
                    <td className="px-4 py-2 text-muted-foreground">{shortTime(attempt.submitted_at || attempt.created_at)}</td>
                    <td className="px-4 py-2 font-mono text-xs">{text(attempt.market_ticker)}</td>
                    <td className="px-4 py-2">{text(attempt.status)}</td>
                    <td className="px-4 py-2 text-muted-foreground">{text(attempt.reason || attempt.guard_reason, "")}</td>
                    <td className="px-4 py-2">{text(attempt.fill_status, "")}</td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                      No live attempts recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-3">
          <Panel title="Risk">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Value label="Daily used" value={money(status.daily_loss_used_dollars)} />
              <Value label="Daily limit" value={money(status.daily_loss_limit_dollars)} />
              <Value label="Market used" value={money(status.market_exposure_used_dollars)} />
              <Value label="Market limit" value={money(status.market_exposure_limit_dollars)} />
            </div>
          </Panel>
          <Panel title="Runtime Config">
            <div className="space-y-2 text-sm">
              <Value label="Version" value={text(config.version)} />
              <Value label="Max order" value={money(config.max_order_dollars)} />
              <Value label="Min edge" value={text(config.min_edge)} />
              <Value label="Min price" value={money(config.min_contract_price)} />
              <Value label="Max markets" value={text(config.max_markets)} />
            </div>
          </Panel>
          <Panel title="Recent Runs">
            <div className="space-y-2">
              {recentRuns.length ? recentRuns.map((run, index) => (
                <div key={index} className="text-sm border-t border-border first:border-0 pt-2 first:pt-0">
                  <div className="font-mono text-xs">{text(run.run_id)}</div>
                  <div className="text-muted-foreground">{text(run.decision_outcome)} · {shortTime(run.generated_at)}</div>
                </div>
              )) : (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <ShieldAlert className="h-4 w-4" />
                  No recent runs.
                </div>
              )}
            </div>
          </Panel>
        </div>
      </section>
    </div>
  )
}

function Metric({ label, value, detail, tone = "muted" }: { label: string; value: string; detail?: string; tone?: "good" | "warn" | "muted" }) {
  const toneClass = tone === "good" ? "text-success" : tone === "warn" ? "text-warning" : "text-foreground"
  return (
    <div className="border border-border rounded-lg bg-card p-4 min-h-24">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-2 text-xl font-semibold ${toneClass}`}>{value}</div>
      {detail && <div className="mt-1 text-xs text-muted-foreground truncate">{detail}</div>}
    </div>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border border-border rounded-lg bg-card p-4">
      <h2 className="text-sm font-medium mb-3">{title}</h2>
      {children}
    </div>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  )
}
