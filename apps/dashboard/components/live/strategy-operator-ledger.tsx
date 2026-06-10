"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  CircleDot,
  Clock3,
  Eye,
  PauseCircle,
  RefreshCw,
  ShieldCheck,
  WifiOff,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { NestedSurface, PanelBody, PanelHeader, PanelSurface } from "@/components/ui/surface"
import { apiGet } from "@/lib/alphadb-api"
import { cn } from "@/lib/utils"

type StrategyHealth = "healthy" | "degraded" | "paused" | "failed" | "unknown"
type LiveState = "enabled" | "disabled" | "no_recent_run" | "unavailable"
type DataState = "available" | "sparse" | "unavailable"
type Tone = "good" | "warn" | "bad" | "muted"

interface StrategyLedgerPayload {
  schema_version: string
  generated_at: string
  fleet_health: FleetHealth
  rows: StrategyLedgerRow[]
}

interface StrategyLedgerRow {
  strategy_id: string
  display_name: string
  health: StrategyHealth
  health_detail: string
  live_state: LiveState
  live_state_detail: string
  data_state: DataState
  latest_run_id: string | null
  latest_run_generated_at: string | null
  latest_decision: LatestDecision
  latest_live_edge_attribution: LiveEdgeAttribution | null
  recent_runs: StrategyRecentRun[]
  risk_summary: RiskSummary
  context_summary: ContextSummary
  decision_outcome: string
  latest_attempt_status: string | null
  latest_attempt_reason: string | null
  live_orders_enabled: boolean | null
  active_config: Record<string, unknown> | null
  config_error: string | null
  status_error: string | null
  recent_runs_error: string | null
}

interface FleetHealth {
  state: StrategyHealth | "unavailable"
  detail: string
  counts: Record<string, number>
  total: number
}

interface LatestDecision {
  outcome: string
  side: string | null
  reason: string | null
  market_ticker: string | null
  run_id: string | null
  generated_at: string | null
}

interface LiveEdgeAttribution {
  side?: string | null
  fair_value?: number | null
  price?: number | null
  fee_per_contract?: number | null
  raw_gap?: number | null
  edge?: number | null
  min_edge?: number | null
  edge_shortfall?: number | null
  edge_margin?: number | null
  edge_cleared?: boolean | null
  side_evaluations?: LiveSideEvaluation[] | null
}

interface LiveSideEvaluation {
  side?: string | null
  selected?: boolean | null
  valid?: boolean | null
  status?: string | null
  reason?: string | null
  comparison_reason?: string | null
  probability?: number | null
  fair_value?: number | null
  price?: number | null
  fee_per_contract?: number | null
  raw_gap?: number | null
  edge?: number | null
  min_edge?: number | null
  edge_shortfall?: number | null
  edge_margin?: number | null
  edge_cleared?: boolean | null
}

interface StrategyRecentRun {
  run_id?: string | null
  generated_at?: string | null
  current_market_ticker?: string | null
  decision_outcome?: string | null
  latest_attempt_status?: string | null
  latest_attempt_reason?: string | null
  fill_status?: string | null
  recent_attempt_count?: number | null
}

interface RiskSummary {
  state: DataState
  detail: string
  daily_loss_used_dollars: number | null
  daily_loss_limit_dollars: number | null
  market_exposure_used_dollars: number | null
  market_exposure_limit_dollars: number | null
}

interface ContextSummary {
  state: string
  detail: string
  active_source: string | null
  active_source_label: string
  latest_run_source: string | null
  latest_run_source_label: string
  latest_run_status: string | null
  external_close_source: string | null
}

const REFRESH_MS = 15_000
const VISIBILITY_STORAGE_KEY = "alphadb.strategyOperatorLedger.hiddenStrategies.v1"

export function StrategyOperatorLedger() {
  const [payload, setPayload] = useState<StrategyLedgerPayload | null>(null)
  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(null)
  const [hiddenStrategyIds, setHiddenStrategyIds] = useState<string[]>([])
  const [visibilityLoaded, setVisibilityLoaded] = useState(false)
  const [visibilityMenuOpen, setVisibilityMenuOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await apiGet<StrategyLedgerPayload>("/live/ledger")
      setPayload(next)
      setSelectedStrategyId((current) => {
        const rows = next.rows || []
        if (!rows.length) return null
        return rows.some((row) => row.strategy_id === current)
          ? current
          : rows[0].strategy_id
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load strategy ledger")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(id)
  }, [load])

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(VISIBILITY_STORAGE_KEY)
      setHiddenStrategyIds(normalizeHiddenStrategyIds(saved ? JSON.parse(saved) : []))
    } catch {
      setHiddenStrategyIds([])
    }
    setVisibilityLoaded(true)
  }, [])

  useEffect(() => {
    if (!visibilityLoaded) return
    try {
      window.localStorage.setItem(VISIBILITY_STORAGE_KEY, JSON.stringify(hiddenStrategyIds))
    } catch {
      // Local visibility is a convenience preference; the ledger still renders without it.
    }
  }, [hiddenStrategyIds, visibilityLoaded])

  const rows = useMemo(() => payload?.rows ?? [], [payload?.rows])
  const hiddenSet = useMemo(() => new Set(hiddenStrategyIds), [hiddenStrategyIds])
  const visibleRows = useMemo(
    () => rows.filter((row) => !hiddenSet.has(row.strategy_id)),
    [hiddenSet, rows],
  )
  const selectedRow =
    visibleRows.find((row) => row.strategy_id === selectedStrategyId) ??
    visibleRows[0] ??
    null
  const fleetStatus = fleetHealth(payload?.fleet_health, visibleRows, loading, error)
  const unavailableCount = visibleRows.filter((row) => row.data_state === "unavailable").length
  const visibleCount = visibleRows.length

  useEffect(() => {
    setSelectedStrategyId((current) => {
      if (!visibleRows.length) return null
      return visibleRows.some((row) => row.strategy_id === current)
        ? current
        : visibleRows[0].strategy_id
    })
  }, [visibleRows])

  const toggleStrategyVisibility = (strategyId: string) => {
    setHiddenStrategyIds((current) =>
      current.includes(strategyId)
        ? current.filter((id) => id !== strategyId)
        : [...current, strategyId],
    )
  }

  const showAllStrategies = () => {
    setHiddenStrategyIds([])
    setVisibilityMenuOpen(false)
  }

  return (
    <div className="min-h-full p-6">
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Live Operations</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Strategy operator ledger | {shortTime(payload?.generated_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <HeaderStatus
            label="Strategies"
            value={rows.length ? `${visibleCount}/${rows.length}` : "--"}
            tone={visibleCount ? "good" : "muted"}
          />
          <HeaderStatus label="Fleet" value={fleetStatus.value} tone={fleetStatus.tone} />
          <HeaderStatus
            label="Sparse"
            value={unavailableCount ? `${unavailableCount} unavailable` : sparseCountLabel(visibleRows)}
            tone={unavailableCount ? "bad" : visibleRows.some((row) => row.data_state === "sparse") ? "warn" : "good"}
          />
          <StrategyVisibilityMenu
            hiddenStrategyIds={hiddenStrategyIds}
            onOpenChange={setVisibilityMenuOpen}
            onShowAll={showAllStrategies}
            onToggleStrategy={toggleStrategyVisibility}
            open={visibilityMenuOpen}
            rows={rows}
          />
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            {loading ? "Refreshing" : "Refresh"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-cockpit-risk/45 bg-cockpit-risk/10 p-3 text-sm text-cockpit-risk">
          {error}
        </div>
      )}

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <PanelSurface className="h-auto min-h-[520px]">
          <PanelHeader className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <CircleDot className="h-4 w-4 text-cockpit-accent-border" />
              <h2 className="text-sm font-medium">Strategy Ledger</h2>
            </div>
            <Badge variant="outline" className="border-field-border/70 bg-surface-inset text-muted-foreground">
              {payload?.schema_version ?? "loading"}
            </Badge>
          </PanelHeader>
          <PanelBody className="p-0">
            {visibleRows.length ? (
              <div className="overflow-auto">
                <div className="min-w-[1180px]">
                  <div className="grid grid-cols-[minmax(190px,1.15fr)_120px_112px_minmax(160px,0.9fr)_150px_150px_minmax(260px,1.5fr)] border-b border-border/80 bg-surface-panel-raised/50 px-4 py-2 text-xs font-medium text-muted-foreground">
                    <span>Strategy</span>
                    <span>Health</span>
                    <span>Live state</span>
                    <span>Decision</span>
                    <span>Risk</span>
                    <span>Context</span>
                    <span>Recent runs</span>
                  </div>
                  {visibleRows.map((row) => (
                    <button
                      className={cn(
                        "grid w-full grid-cols-[minmax(190px,1.15fr)_120px_112px_minmax(160px,0.9fr)_150px_150px_minmax(260px,1.5fr)] items-center gap-0 border-b border-border/70 px-4 py-3 text-left text-sm transition last:border-0 hover:bg-cockpit-accent-soft/70",
                        selectedRow?.strategy_id === row.strategy_id && "bg-cockpit-accent-soft/60",
                      )}
                      key={row.strategy_id}
                      onClick={() => setSelectedStrategyId(row.strategy_id)}
                      type="button"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium text-foreground">{row.display_name}</div>
                        <div className="truncate font-mono text-xs text-muted-foreground">{row.strategy_id}</div>
                      </div>
                      <HealthBadge health={row.health} />
                      <StateBadge state={row.live_state} />
                      <div className="min-w-0">
                        <div className="truncate text-foreground">{decisionLabel(row.latest_decision)}</div>
                        <div className="mt-1 truncate text-xs text-muted-foreground">
                          {value(row.latest_decision.reason, "")}
                        </div>
                      </div>
                      <RiskMeter summary={row.risk_summary} />
                      <div className="min-w-0">
                        <div className="truncate text-foreground">{row.context_summary.latest_run_source_label}</div>
                        <div className="mt-1 truncate text-xs text-muted-foreground">
                          {value(row.context_summary.latest_run_status ?? row.context_summary.state)}
                        </div>
                      </div>
                      <RecentRunChips runs={row.recent_runs} />
                    </button>
                  ))}
                </div>
              </div>
            ) : rows.length ? (
              <SparseLedger loading={false} hidden onShowAll={showAllStrategies} />
            ) : (
              <SparseLedger loading={loading} />
            )}
          </PanelBody>
        </PanelSurface>

        <StrategyDetailRail row={selectedRow} />
      </section>
    </div>
  )
}

function StrategyDetailRail({ row }: { row: StrategyLedgerRow | null }) {
  if (!row) {
    return (
      <PanelSurface className="h-auto min-h-[520px]">
        <PanelBody className="flex flex-col items-center justify-center gap-3 text-center">
          <WifiOff className="h-5 w-5 text-muted-foreground" />
          <div>
            <div className="text-sm font-medium text-foreground">No strategy selected</div>
            <div className="mt-1 text-sm text-muted-foreground">No ledger rows are available.</div>
          </div>
        </PanelBody>
      </PanelSurface>
    )
  }

  return (
    <PanelSurface className="h-auto min-h-[520px]">
      <PanelHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-medium text-foreground">{row.display_name}</h2>
            <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{row.strategy_id}</p>
          </div>
          <HealthBadge health={row.health} />
        </div>
      </PanelHeader>
      <PanelBody className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <MiniValue label="Live state" value={stateLabel(row.live_state)} />
          <MiniValue label="Data" value={dataStateLabel(row.data_state)} />
          <MiniValue label="Decision" value={decisionLabel(row.latest_decision)} />
          <MiniValue label="Attempt" value={value(row.latest_attempt_status)} />
          <MiniValue label="Config" value={configVersion(row.active_config)} />
          <MiniValue label="Orders" value={ordersLabel(row.live_orders_enabled)} />
        </div>

        <NestedSurface className="p-3">
          <div className="text-xs font-medium text-muted-foreground">Health detail</div>
          <div className="mt-2 text-sm text-foreground">{row.health_detail}</div>
          <div className="mt-2 text-xs text-muted-foreground">{row.live_state_detail}</div>
        </NestedSurface>

        <NestedSurface className="p-3">
          <div className="text-xs font-medium text-muted-foreground">Latest run</div>
          <div className="mt-2 space-y-1 text-sm">
            <KeyValue label="Run" value={value(row.latest_run_id)} />
            <KeyValue label="Observed" value={shortTime(row.latest_run_generated_at)} />
            <KeyValue label="Reason" value={value(row.latest_attempt_reason)} />
          </div>
        </NestedSurface>

        <EdgeAttributionRail attribution={row.latest_live_edge_attribution} />

        <NestedSurface className="p-3">
          <div className="text-xs font-medium text-muted-foreground">Risk</div>
          <div className="mt-2 space-y-1 text-sm">
            <KeyValue label="State" value={dataStateLabel(row.risk_summary.state)} />
            <KeyValue label="Daily loss" value={riskMoney(row.risk_summary.daily_loss_used_dollars, row.risk_summary.daily_loss_limit_dollars)} />
            <KeyValue label="Market exposure" value={riskMoney(row.risk_summary.market_exposure_used_dollars, row.risk_summary.market_exposure_limit_dollars)} />
          </div>
          <div className="mt-2 text-xs text-muted-foreground">{row.risk_summary.detail}</div>
        </NestedSurface>

        <NestedSurface className="p-3">
          <div className="text-xs font-medium text-muted-foreground">Context</div>
          <div className="mt-2 space-y-1 text-sm">
            <KeyValue label="Active" value={row.context_summary.active_source_label} />
            <KeyValue label="Latest run" value={row.context_summary.latest_run_source_label} />
            <KeyValue label="Status" value={value(row.context_summary.latest_run_status ?? row.context_summary.state)} />
            <KeyValue label="Close source" value={value(row.context_summary.external_close_source)} />
          </div>
          <div className="mt-2 text-xs text-muted-foreground">{row.context_summary.detail}</div>
        </NestedSurface>

        <NestedSurface className="p-3">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs font-medium text-muted-foreground">Recent runs</div>
            <div className="font-mono text-xs text-muted-foreground">{row.recent_runs.length}</div>
          </div>
          <RecentRunList runs={row.recent_runs} />
          {row.recent_runs_error && (
            <div className="mt-2 font-mono text-xs text-cockpit-risk">{row.recent_runs_error}</div>
          )}
        </NestedSurface>

        {(row.status_error || row.config_error) && (
          <NestedSurface className="border-cockpit-risk/35 bg-cockpit-risk/10 p-3">
            <div className="text-xs font-medium text-cockpit-risk">Unavailable inputs</div>
            <div className="mt-2 space-y-1 font-mono text-xs text-cockpit-risk">
              {row.status_error && <div>{row.status_error}</div>}
              {row.config_error && <div>{row.config_error}</div>}
            </div>
          </NestedSurface>
        )}
      </PanelBody>
    </PanelSurface>
  )
}

function SparseLedger({
  hidden = false,
  loading,
  onShowAll,
}: {
  hidden?: boolean
  loading: boolean
  onShowAll?: () => void
}) {
  const title = loading
    ? "Loading strategy ledger"
    : hidden
      ? "No visible strategies"
      : "No live strategies"
  const detail = loading
    ? "Waiting for the AlphaDB API read."
    : hidden
      ? "All strategy ledger rows are hidden by local Cockpit visibility."
      : "No strategy ledger rows returned by the AlphaDB API."
  return (
    <div className="flex min-h-[460px] flex-col items-center justify-center gap-3 p-6 text-center">
      <Clock3 className="h-5 w-5 text-muted-foreground" />
      <div>
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="mt-1 text-sm text-muted-foreground">{detail}</div>
      </div>
      {hidden && onShowAll && (
        <Button variant="outline" size="sm" onClick={onShowAll}>
          <Eye className="h-4 w-4" />
          Show all
        </Button>
      )}
    </div>
  )
}

function StrategyVisibilityMenu({
  hiddenStrategyIds,
  onOpenChange,
  onShowAll,
  onToggleStrategy,
  open,
  rows,
}: {
  hiddenStrategyIds: string[]
  onOpenChange: (open: boolean) => void
  onShowAll: () => void
  onToggleStrategy: (strategyId: string) => void
  open: boolean
  rows: StrategyLedgerRow[]
}) {
  const hiddenSet = new Set(hiddenStrategyIds)
  const visibleCount = rows.filter((row) => !hiddenSet.has(row.strategy_id)).length
  return (
    <div className="relative">
      <Button
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => onOpenChange(!open)}
        size="sm"
        title="Show or hide strategies in this browser"
        type="button"
        variant="outline"
      >
        <Eye className="h-4 w-4" />
        Strategies
        <span className="font-mono text-xs text-muted-foreground">
          {rows.length ? `${visibleCount}/${rows.length}` : "--"}
        </span>
      </Button>
      {open && (
        <div className="fixed left-20 right-4 top-44 z-30 overflow-hidden rounded-lg border border-field-border/70 bg-surface-panel text-popover-foreground shadow-2xl sm:absolute sm:left-auto sm:right-0 sm:top-8 sm:w-72">
          <div className="border-b border-border/90 bg-surface-panel-raised px-3 py-2 text-xs font-medium text-muted-foreground">
            Visible strategies
          </div>
          <div className="max-h-80 overflow-auto p-1">
            {rows.length ? rows.map((row) => (
              <label
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm transition hover:bg-cockpit-accent-soft hover:text-foreground"
                key={row.strategy_id}
              >
                <input
                  checked={!hiddenSet.has(row.strategy_id)}
                  className="size-4 accent-cockpit-accent-border"
                  onChange={() => onToggleStrategy(row.strategy_id)}
                  type="checkbox"
                />
                <span className="min-w-0 flex-1 truncate">{row.display_name}</span>
                <HealthIcon health={row.health} />
              </label>
            )) : (
              <div className="px-2 py-3 text-sm text-muted-foreground">No strategies returned.</div>
            )}
          </div>
          {hiddenStrategyIds.length > 0 && (
            <div className="border-t border-border/90 p-2">
              <Button variant="ghost" size="sm" className="w-full justify-start" onClick={onShowAll}>
                <Eye className="h-4 w-4" />
                Show all
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function HealthBadge({ health }: { health: StrategyHealth }) {
  return (
    <Badge
      className={cn(
        "border",
        health === "healthy" && "border-success/35 bg-success/10 text-success",
        health === "degraded" && "border-warning/35 bg-warning/10 text-warning",
        health === "paused" && "border-field-border/70 bg-surface-inset text-muted-foreground",
        health === "failed" && "border-cockpit-risk/35 bg-cockpit-risk/10 text-cockpit-risk",
        health === "unknown" && "border-field-border/70 bg-surface-inset text-muted-foreground",
      )}
      variant="outline"
    >
      <HealthIcon health={health} />
      {health}
    </Badge>
  )
}

function HealthIcon({ health }: { health: StrategyHealth }) {
  if (health === "healthy") return <ShieldCheck className="h-3.5 w-3.5 text-success" />
  if (health === "degraded") return <AlertTriangle className="h-3.5 w-3.5 text-warning" />
  if (health === "failed") return <AlertTriangle className="h-3.5 w-3.5 text-cockpit-risk" />
  if (health === "paused") return <PauseCircle className="h-3.5 w-3.5 text-muted-foreground" />
  return <CircleDot className="h-3.5 w-3.5 text-muted-foreground" />
}

function StateBadge({ state }: { state: LiveState }) {
  return (
    <span className="inline-flex w-fit items-center gap-1.5 rounded-md border border-field-border/70 bg-surface-inset px-2 py-1 text-xs text-muted-foreground">
      <span className={cn("h-2 w-2 rounded-full", stateDotClass(state))} />
      {stateLabel(state)}
    </span>
  )
}

function HeaderStatus({
  label,
  tone,
  value: statusValue,
}: {
  label: string
  tone: Tone
  value: string
}) {
  return (
    <div
      aria-label={`${label}: ${statusValue}`}
      className="inline-flex h-7 items-center gap-2 rounded-md border border-field-border/60 bg-surface-panel-raised px-2 text-xs text-muted-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.03)]"
    >
      <span>{label}</span>
      <span className="font-mono text-foreground">{statusValue}</span>
      <span className={cn("h-2 w-2 rounded-full", toneDotClass(tone))} />
    </div>
  )
}

function MiniValue({ label, value: metricValue }: { label: string; value: string }) {
  return (
    <NestedSurface className="min-h-16 min-w-0 p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-medium text-foreground">{metricValue}</div>
    </NestedSurface>
  )
}

function KeyValue({ label, value: itemValue }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate font-mono text-xs text-foreground">{itemValue}</span>
    </div>
  )
}

function RiskMeter({ summary }: { summary: RiskSummary }) {
  const used = Number(summary.daily_loss_used_dollars)
  const limit = Number(summary.daily_loss_limit_dollars)
  const pct = Number.isFinite(used) && Number.isFinite(limit) && limit > 0
    ? Math.max(0, Math.min(100, (used / limit) * 100))
    : 0
  return (
    <div className="min-w-0">
      <div className="truncate font-mono text-xs text-foreground">
        {riskMoney(summary.daily_loss_used_dollars, summary.daily_loss_limit_dollars)}
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-inset">
        <div className="h-full rounded-full bg-cockpit-accent-border" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function RecentRunChips({ runs }: { runs: StrategyRecentRun[] }) {
  if (!runs.length) {
    return <div className="text-sm text-muted-foreground">--</div>
  }
  return (
    <div className="flex min-w-0 flex-wrap gap-1.5">
      {runs.slice(0, 3).map((run, index) => (
        <span
          className="inline-flex max-w-52 items-center gap-1.5 rounded-md border border-field-border/70 bg-surface-inset px-2 py-1 text-xs text-muted-foreground"
          key={run.run_id ?? index}
          title={run.latest_attempt_reason ?? run.decision_outcome ?? undefined}
        >
          <span className={cn("h-2 w-2 shrink-0 rounded-full", outcomeDotClass(run.decision_outcome))} />
          <span className="truncate">{shortTime(run.generated_at)}</span>
          <span className="truncate text-foreground">{value(run.decision_outcome)}</span>
        </span>
      ))}
    </div>
  )
}

function RecentRunList({ runs }: { runs: StrategyRecentRun[] }) {
  if (!runs.length) {
    return (
      <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
        <Clock3 className="h-4 w-4" />
        No recent runs.
      </div>
    )
  }
  return (
    <div className="mt-2 space-y-2">
      {runs.map((run, index) => (
        <div
          className="rounded-md border border-border/80 bg-surface-panel px-2 py-1.5"
          key={run.run_id ?? index}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-sm text-foreground">{value(run.decision_outcome)}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{shortTime(run.generated_at)}</span>
          </div>
          <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
            {value(run.current_market_ticker)} | {value(run.run_id)}
          </div>
          {run.latest_attempt_reason && (
            <div className="mt-1 truncate text-xs text-muted-foreground">
              {run.latest_attempt_reason}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function EdgeAttributionRail({ attribution }: { attribution: LiveEdgeAttribution | null }) {
  const evaluations = sideEvaluations(attribution)
  return (
    <NestedSurface className="p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-muted-foreground">YES / NO edge comparison</div>
        <div className="font-mono text-xs text-muted-foreground">
          {evaluations.length ? `${evaluations.length} side${evaluations.length === 1 ? "" : "s"}` : "--"}
        </div>
      </div>
      {evaluations.length ? (
        <div className="mt-2 grid gap-2">
          {evaluations.map((evaluation, index) => (
            <div
              className={cn(
                "rounded-md border px-2 py-2",
                evaluation.selected
                  ? "border-cockpit-accent-border bg-cockpit-accent-soft"
                  : "border-border/80 bg-surface-panel",
              )}
              key={`${value(evaluation.side, "side")}-${index}`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-xs font-medium uppercase text-foreground">
                  {value(evaluation.side)}
                </span>
                <span className="rounded-sm border border-field-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                  {evaluation.selected ? "selected" : value(evaluation.status, "available")}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-x-2 gap-y-1">
                <SideMetric label="Fair" value={optionalPercent(evaluation.fair_value ?? evaluation.probability)} />
                <SideMetric label="Ask" value={optionalPercent(evaluation.price)} />
                <SideMetric label="Edge" value={optionalPercent(evaluation.edge)} />
                <SideMetric label="Raw" value={optionalPercent(evaluation.raw_gap)} />
                <SideMetric label="Fee" value={optionalPercent(evaluation.fee_per_contract)} />
                <SideMetric label="Gap" value={edgeGapText(evaluation)} />
              </div>
              <div className="mt-2 truncate font-mono text-[11px] text-muted-foreground">
                {value(evaluation.comparison_reason || evaluation.reason)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-2 text-sm text-muted-foreground">No live edge attribution recorded.</div>
      )}
    </NestedSurface>
  )
}

function SideMetric({ label, value: metricValue }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="truncate font-mono text-xs text-foreground">{metricValue}</div>
    </div>
  )
}

function sideEvaluations(attribution: LiveEdgeAttribution | null): LiveSideEvaluation[] {
  if (!attribution) return []
  if (Array.isArray(attribution.side_evaluations) && attribution.side_evaluations.length) {
    return attribution.side_evaluations.filter(isLiveSideEvaluation)
  }
  if (!hasLegacyAttribution(attribution)) return []
  return [{
    side: attribution.side,
    selected: Boolean(attribution.side),
    valid: attribution.price !== null && attribution.price !== undefined,
    status: attribution.edge_cleared ? "cleared" : "legacy_selected_side",
    reason: "legacy_selected_side_attribution",
    comparison_reason: "legacy_selected_side_attribution",
    probability: attribution.fair_value,
    fair_value: attribution.fair_value,
    price: attribution.price,
    fee_per_contract: attribution.fee_per_contract,
    raw_gap: attribution.raw_gap,
    edge: attribution.edge,
    min_edge: attribution.min_edge,
    edge_shortfall: attribution.edge_shortfall,
    edge_margin: attribution.edge_margin,
    edge_cleared: attribution.edge_cleared,
  }]
}

function isLiveSideEvaluation(value: unknown): value is LiveSideEvaluation {
  return Boolean(value && typeof value === "object" && !Array.isArray(value))
}

function hasLegacyAttribution(attribution: LiveEdgeAttribution) {
  return Boolean(
    attribution.side ||
    (attribution.edge !== null && attribution.edge !== undefined) ||
    (attribution.price !== null && attribution.price !== undefined),
  )
}

function optionalPercent(input: unknown) {
  if (input === null || input === undefined || input === "") return "--"
  const number = Number(input)
  if (!Number.isFinite(number)) return "--"
  return `${(number * 100).toFixed(2)}%`
}

function edgeGapText(evaluation: LiveSideEvaluation) {
  const shortfall = Number(evaluation.edge_shortfall)
  if (Number.isFinite(shortfall) && shortfall > 0) {
    return `short ${optionalPercent(shortfall)}`
  }
  const margin = Number(evaluation.edge_margin)
  if (Number.isFinite(margin)) {
    return `${margin >= 0 ? "+" : ""}${optionalPercent(margin)}`
  }
  const edge = Number(evaluation.edge)
  const minEdge = Number(evaluation.min_edge)
  if (Number.isFinite(edge) && Number.isFinite(minEdge)) {
    const derivedMargin = edge - minEdge
    if (derivedMargin < 0) return `short ${optionalPercent(-derivedMargin)}`
    return `+${optionalPercent(derivedMargin)}`
  }
  return "--"
}

function fleetHealth(
  serverFleet: FleetHealth | undefined,
  rows: StrategyLedgerRow[],
  loading: boolean,
  error: string | null,
) {
  if (error) return { value: "API error", tone: "bad" as Tone }
  if (!rows.length) return { value: loading ? "Checking" : "Sparse", tone: "muted" as Tone }
  if (serverFleet?.state === "failed") return { value: "Failed", tone: "bad" as Tone }
  if (serverFleet?.state === "unavailable") return { value: "Unavailable", tone: "bad" as Tone }
  if (serverFleet?.state === "degraded") return { value: "Degraded", tone: "warn" as Tone }
  if (rows.some((row) => row.health === "failed")) return { value: "Failed", tone: "bad" as Tone }
  const unknown = rows.filter((row) => row.health === "unknown").length
  const paused = rows.filter((row) => row.health === "paused").length
  const degraded = rows.filter((row) => row.health === "degraded").length
  if (degraded) return { value: `${degraded} degraded`, tone: "warn" as Tone }
  if (unknown) return { value: `${unknown} unknown`, tone: "warn" as Tone }
  if (paused) return { value: `${paused} paused`, tone: "warn" as Tone }
  return { value: "OK", tone: "good" as Tone }
}

function normalizeHiddenStrategyIds(value: unknown) {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  const normalized: string[] = []
  for (const item of value) {
    const id = typeof item === "string" ? item.trim() : ""
    if (!id || seen.has(id)) continue
    seen.add(id)
    normalized.push(id)
  }
  return normalized
}

function value(input: unknown, fallback = "--") {
  if (input === null || input === undefined || input === "") return fallback
  return String(input)
}

function shortTime(input: unknown) {
  if (!input) return "--"
  const date = new Date(String(input))
  if (Number.isNaN(date.getTime())) return String(input)
  return date.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function stateLabel(state: LiveState) {
  if (state === "enabled") return "Enabled"
  if (state === "disabled") return "Disabled"
  if (state === "no_recent_run") return "No run"
  return "Unavailable"
}

function dataStateLabel(state: DataState) {
  if (state === "available") return "Available"
  if (state === "sparse") return "Sparse"
  return "Unavailable"
}

function decisionLabel(decision: LatestDecision) {
  const outcome = value(decision.outcome)
  const side = decision.side ? ` ${decision.side}` : ""
  return `${outcome}${side}`
}

function riskMoney(used: number | null, limit: number | null) {
  if (used === null || limit === null) return "--"
  return `${money(used)} / ${money(limit)}`
}

function money(input: unknown) {
  const number = Number(input)
  if (!Number.isFinite(number)) return "--"
  return `$${number.toFixed(2)}`
}

function ordersLabel(enabled: boolean | null) {
  if (enabled === true) return "Enabled"
  if (enabled === false) return "Disabled"
  return "--"
}

function configVersion(config: Record<string, unknown> | null) {
  const version = config?.version
  return version === null || version === undefined ? "--" : `v${version}`
}

function sparseCountLabel(rows: StrategyLedgerRow[]) {
  const sparse = rows.filter((row) => row.data_state === "sparse").length
  return sparse ? `${sparse} sparse` : "0"
}

function stateDotClass(state: LiveState) {
  if (state === "enabled") return "bg-success"
  if (state === "disabled") return "bg-warning"
  if (state === "unavailable") return "bg-destructive"
  return "bg-muted-foreground"
}

function toneDotClass(tone: Tone) {
  if (tone === "good") return "bg-success"
  if (tone === "warn") return "bg-warning"
  if (tone === "bad") return "bg-destructive"
  return "bg-muted-foreground"
}

function outcomeDotClass(outcome: unknown) {
  const value = String(outcome || "")
  if (value === "submitted" || value === "trade" || value === "filled") return "bg-success"
  if (value === "skipped" || value === "no_recent_run") return "bg-cockpit-accent-border"
  if (value === "blocked") return "bg-warning"
  if (value === "error" || value === "failed") return "bg-destructive"
  return "bg-muted-foreground"
}
