"use client"

import { useEffect, useState, type ReactNode } from "react"
import { apiGet } from "@/lib/alphadb-api"
import { Button } from "@/components/ui/button"
import { Activity, CircleDollarSign, RefreshCw, ShieldAlert, TrendingUp } from "lucide-react"

type Tone = "good" | "warn" | "bad" | "muted"

interface PerformancePayload {
  schema_version: string
  strategy: string
  market_series: string
  generated_at_utc: string
  data_status: string
  data_status_detail: string
  config: {
    status: string
    version: number | null
    config_id: string | null
    limits: Record<string, number | null>
  }
  freshness: {
    status: string
    latest_run_generated_at_utc: string | null
    age_seconds: number | null
    stale: boolean
    stale_after_seconds: number
  }
  risk_budget: {
    status: string
    daily_loss_used_dollars: number | null
    daily_loss_limit_dollars: number | null
    daily_loss_remaining_dollars: number | null
    daily_loss_usage_fraction: number | null
    market_exposure_used_dollars: number | null
    market_exposure_limit_dollars: number | null
    market_exposure_usage_fraction: number | null
  }
  execution: {
    data_status: string
    data_status_detail: string
    counts: Record<"submitted" | "skipped" | "rejected" | "filled" | "no_fill" | "unknown", number>
    skip_reasons: Array<{ reason: string; count: number }>
    recent_runs: RecentRun[]
  }
  pnl: {
    status: string
    status_detail: string
    settlement_state: string
    fees_status: string
    net_pnl_dollars: number | null
    realized_pnl_dollars: number | null
    unrealized_pnl_dollars: number | null
    fees_dollars: number | null
    unsettled_exposure_dollars: number | null
    filled_contracts: number
    order_count: number
    fill_count: number
    position_count: number
    latest_observed_at_utc: string | null
    reconciliation_counts: Record<string, number>
  }
  recent_runs: RecentRun[]
}

interface RecentRun {
  run_id: string | null
  generated_at_utc: string | null
  market_ticker: string | null
  decision_outcome: string | null
  selected_side: string | null
  skip_reason: string | null
  attempt_status: string | null
  attempt_reason: string | null
  fill_status: string | null
  config_version: number | null
  daily_loss_used_dollars: number | null
  market_exposure_used_dollars: number | null
}

function text(value: unknown, fallback = "--") {
  if (value === null || value === undefined || value === "") return fallback
  return String(value)
}

function optionalMoney(value: unknown) {
  if (value === null || value === undefined || value === "") return "--"
  const number = Number(value)
  if (!Number.isFinite(number)) return "--"
  return `$${number.toFixed(2)}`
}

function optionalPercent(value: unknown) {
  if (value === null || value === undefined || value === "") return "--"
  const number = Number(value)
  if (!Number.isFinite(number)) return "--"
  return `${(number * 100).toFixed(0)}%`
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

export function PerformanceSection() {
  const [payload, setPayload] = useState<PerformancePayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setPayload(await apiGet<PerformancePayload>("/performance"))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load performance")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = window.setInterval(load, 30000)
    return () => window.clearInterval(id)
  }, [])

  const pnl = payload?.pnl
  const execution = payload?.execution
  const risk = payload?.risk_budget
  const recentRuns = payload?.recent_runs || []
  const statusTone = toneForStatus(payload?.data_status, loading, error)

  return (
    <div className="p-6 space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold text-foreground">Performance</h1>
            <StatusDot tone={statusTone} label={text(payload?.data_status, loading ? "loading" : "unknown")} />
          </div>
          <p className="text-sm text-muted-foreground">
            {text(payload?.strategy, "strategy unknown")} · {text(payload?.market_series, "series unknown")} · {shortTime(payload?.generated_at_utc)}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="border border-destructive/40 bg-destructive/10 rounded-lg p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <section className="grid gap-3 md:grid-cols-4">
        <Metric
          label="Net PnL"
          value={optionalMoney(pnl?.net_pnl_dollars)}
          detail={`${text(pnl?.status, "unknown")} · ${text(pnl?.settlement_state, "settlement unknown")}`}
          tone={moneyTone(pnl?.net_pnl_dollars, pnl?.status)}
        />
        <Metric
          label="Realized / Unrealized"
          value={`${optionalMoney(pnl?.realized_pnl_dollars)} / ${optionalMoney(pnl?.unrealized_pnl_dollars)}`}
          detail={`${text(pnl?.filled_contracts, "0")} filled contracts`}
        />
        <Metric
          label="Fees"
          value={optionalMoney(pnl?.fees_dollars)}
          detail={text(pnl?.fees_status, "unknown")}
        />
        <Metric
          label="Exposure"
          value={optionalMoney(pnl?.unsettled_exposure_dollars)}
          detail={`${optionalMoney(risk?.market_exposure_used_dollars)} / ${optionalMoney(risk?.market_exposure_limit_dollars)} market risk`}
        />
      </section>

      <section className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-3">
          <Panel
            title="Recent Run Trend"
            icon={<TrendingUp className="h-4 w-4 text-muted-foreground" />}
          >
            <TrendStrip runs={recentRuns} />
          </Panel>

          <Panel
            title="Recent Runs"
            icon={<Activity className="h-4 w-4 text-muted-foreground" />}
          >
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="text-left py-2 pr-3 font-medium">Time</th>
                    <th className="text-left py-2 pr-3 font-medium">Market</th>
                    <th className="text-left py-2 pr-3 font-medium">Outcome</th>
                    <th className="text-left py-2 pr-3 font-medium">Attempt</th>
                    <th className="text-left py-2 pr-3 font-medium">Fill</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.length ? recentRuns.map((run, index) => (
                    <tr key={`${run.run_id || "run"}-${index}`} className="border-b border-border/70 last:border-0">
                      <td className="py-2 pr-3 text-muted-foreground">{shortTime(run.generated_at_utc)}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{text(run.market_ticker)}</td>
                      <td className="py-2 pr-3">{text(run.decision_outcome)}</td>
                      <td className="py-2 pr-3 text-muted-foreground">{text(run.attempt_status || run.attempt_reason)}</td>
                      <td className="py-2 pr-3">{text(run.fill_status)}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-muted-foreground">
                        No recent runs.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        <div className="space-y-3">
          <Panel
            title="Execution Outcomes"
            icon={<CircleDollarSign className="h-4 w-4 text-muted-foreground" />}
          >
            <div className="space-y-2 text-sm">
              {(["submitted", "filled", "no_fill", "skipped", "rejected", "unknown"] as const).map((key) => (
                <Value key={key} label={labelForCount(key)} value={text(execution?.counts?.[key], "0")} />
              ))}
            </div>
          </Panel>

          <Panel title="Risk Budget">
            <div className="space-y-2 text-sm">
              <Value label="Daily used" value={optionalMoney(risk?.daily_loss_used_dollars)} />
              <Value label="Daily limit" value={optionalMoney(risk?.daily_loss_limit_dollars)} />
              <Value label="Daily remaining" value={optionalMoney(risk?.daily_loss_remaining_dollars)} />
              <Value label="Daily usage" value={optionalPercent(risk?.daily_loss_usage_fraction)} />
              <Value label="Market usage" value={optionalPercent(risk?.market_exposure_usage_fraction)} />
            </div>
          </Panel>

          <Panel title="Skip Reasons">
            <div className="space-y-2 text-sm">
              {execution?.skip_reasons?.length ? execution.skip_reasons.map((row) => (
                <Value key={row.reason} label={row.reason} value={String(row.count)} />
              )) : (
                <EmptyLine>No skip reasons recorded.</EmptyLine>
              )}
            </div>
          </Panel>

          <Panel title="Data Freshness">
            <div className="space-y-2 text-sm">
              <Value label="Latest run" value={shortTime(payload?.freshness.latest_run_generated_at_utc)} />
              <Value label="Age" value={payload?.freshness.age_seconds === null || payload?.freshness.age_seconds === undefined ? "--" : `${payload.freshness.age_seconds}s`} />
              <Value label="Latest PnL row" value={shortTime(pnl?.latest_observed_at_utc)} />
              <Value label="Config" value={payload?.config.version ? `v${payload.config.version}` : text(payload?.config.status)} />
            </div>
            {payload?.data_status_detail && (
              <div className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{payload.data_status_detail}</span>
              </div>
            )}
          </Panel>
        </div>
      </section>
    </div>
  )
}

function TrendStrip({ runs }: { runs: RecentRun[] }) {
  const visible = runs.slice(0, 24).reverse()
  if (!visible.length) {
    return <EmptyLine>No trend yet.</EmptyLine>
  }
  return (
    <div className="grid grid-cols-12 gap-1 md:grid-cols-[repeat(24,minmax(0,1fr))]">
      {visible.map((run, index) => (
        <div
          key={`${run.run_id || "run"}-${index}`}
          aria-label={`${text(run.decision_outcome)} ${shortTime(run.generated_at_utc)}`}
          className={`h-8 rounded-sm ${trendClass(run)}`}
          title={`${text(run.decision_outcome)} · ${text(run.market_ticker)} · ${shortTime(run.generated_at_utc)}`}
        />
      ))}
    </div>
  )
}

function Metric({ label, value, detail, tone = "muted" }: { label: string; value: string; detail?: string; tone?: Tone }) {
  return (
    <div className="border border-border rounded-lg bg-card p-4 min-h-24">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-2 text-xl font-semibold ${toneTextClass(tone)}`}>{value}</div>
      {detail && <div className="mt-1 text-xs text-muted-foreground truncate">{detail}</div>}
    </div>
  )
}

function Panel({ title, icon, children }: { title: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="border border-border rounded-lg bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        {icon}
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      {children}
    </div>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-h-6 items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-xs text-foreground">{value}</span>
    </div>
  )
}

function EmptyLine({ children }: { children: ReactNode }) {
  return <div className="text-sm text-muted-foreground">{children}</div>
}

function StatusDot({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`h-2 w-2 rounded-full ${toneDotClass(tone)}`} />
      {label}
    </span>
  )
}

function toneForStatus(status: string | undefined, loading: boolean, error: string | null): Tone {
  if (error) return "bad"
  if (loading && !status) return "warn"
  if (status === "ok") return "good"
  if (status === "stale" || status === "partial" || status === "empty") return "warn"
  return "muted"
}

function moneyTone(value: unknown, status: string | undefined): Tone {
  if (status === "unavailable") return "muted"
  const number = Number(value)
  if (!Number.isFinite(number)) return "warn"
  if (number > 0) return "good"
  if (number < 0) return "bad"
  return "muted"
}

function trendClass(run: RecentRun) {
  if (run.fill_status === "filled") return "bg-success"
  if (run.fill_status === "no_fill") return "bg-warning"
  if (run.decision_outcome === "skipped") return "bg-muted-foreground"
  if (run.decision_outcome === "rejected" || run.decision_outcome === "error") return "bg-destructive"
  if (run.decision_outcome === "submitted") return "bg-chart-1"
  return "bg-muted"
}

function toneTextClass(tone: Tone) {
  if (tone === "good") return "text-success"
  if (tone === "warn") return "text-warning"
  if (tone === "bad") return "text-destructive"
  return "text-foreground"
}

function toneDotClass(tone: Tone) {
  if (tone === "good") return "bg-success"
  if (tone === "warn") return "bg-warning"
  if (tone === "bad") return "bg-destructive"
  return "bg-muted-foreground"
}

function labelForCount(key: string) {
  if (key === "no_fill") return "No fill"
  return key.charAt(0).toUpperCase() + key.slice(1)
}
