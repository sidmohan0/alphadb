"use client"

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { apiGet, apiPost } from "@/lib/alphadb-api"
import { Button } from "@/components/ui/button"
import { useSelectedStrategy } from "@/components/strategy/strategy-context"
import { Activity, RefreshCw, Save, ShieldAlert, Square } from "lucide-react"

interface LivePayload {
  strategy?: string
  strategy_metadata?: Record<string, unknown>
  health?: {
    ok: boolean
    environment: string
    generated_at_utc: string
    components: Array<{ name: string; status: string; detail: string }>
  }
  active_config?: Record<string, unknown>
  config_history?: Array<Record<string, unknown>>
  portfolio_balance?: {
    status: string
    source: string
    portfolio_balance_dollars: number | null
    cash_dollars: number | null
    assets_dollars: number | null
    observed_at_utc: string | null
    stale: boolean
    detail: string | null
  }
  live_status?: Record<string, unknown>
  market_context?: Record<string, unknown>
  recent_runs?: Array<Record<string, unknown>>
}

interface SaveConfigResponse {
  ok?: boolean
  active_config?: Record<string, unknown>
  config_history?: Array<Record<string, unknown>>
}

type Tone = "good" | "warn" | "bad" | "muted"

const CONFIG_FIELDS = [
  { key: "max_order_dollars", label: "Max order", min: "0.01", max: undefined, step: "0.01", integer: false },
  { key: "max_market_exposure_dollars", label: "Market exposure", min: "0.01", max: undefined, step: "0.01", integer: false },
  { key: "max_daily_loss_dollars", label: "Daily loss", min: "0.01", max: undefined, step: "0.01", integer: false },
  { key: "min_edge", label: "Min edge", min: "0", max: "1", step: "0.0001", integer: false },
  { key: "min_contract_price", label: "Min price", min: "0", max: "1", step: "0.01", integer: false },
  { key: "max_markets", label: "Max markets", min: "1", max: "500", step: "1", integer: true },
] as const
const MARKET_CONTEXT_OPTIONS = [
  { key: "coinbase_primary", label: "Coinbase primary" },
  { key: "brti_primary", label: "BRTI primary" },
  { key: "fixture", label: "Fixture" },
] as const

type ConfigFieldKey = (typeof CONFIG_FIELDS)[number]["key"]
type ConfigFormKey = ConfigFieldKey | "market_context_source"
type ConfigFormValues = Record<ConfigFormKey, string>
type ConfigErrors = Partial<Record<ConfigFormKey, string>>

const EMPTY_CONFIG_FORM = {
  ...CONFIG_FIELDS.reduce((values, field) => {
    values[field.key] = ""
    return values
  }, {} as Record<ConfigFieldKey, string>),
  market_context_source: "coinbase_primary",
}

function text(value: unknown, fallback = "--") {
  if (value === null || value === undefined || value === "") return fallback
  return String(value)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function money(value: unknown) {
  const number = Number(value || 0)
  return `$${number.toFixed(2)}`
}

function optionalMoney(value: unknown) {
  if (value === null || value === undefined || value === "") return "--"
  const number = Number(value)
  if (!Number.isFinite(number)) return "--"
  return `$${number.toFixed(2)}`
}

function optionalNumber(value: unknown, digits = 2) {
  if (value === null || value === undefined || value === "") return "--"
  const number = Number(value)
  if (!Number.isFinite(number)) return "--"
  return number.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function seconds(value: unknown) {
  if (value === null || value === undefined || value === "") return "--"
  const number = Number(value)
  if (!Number.isFinite(number)) return "--"
  if (number < 1) return `${Math.round(number * 1000)}ms`
  return `${number.toFixed(number >= 10 ? 0 : 1)}s`
}

function sourceLabel(value: unknown) {
  const source = String(value || "")
  return MARKET_CONTEXT_OPTIONS.find((option) => option.key === source)?.label || text(source)
}

function basisText(dollars: unknown, pct: unknown) {
  const dollarsNumber = Number(dollars)
  const pctNumber = Number(pct)
  if (!Number.isFinite(dollarsNumber)) return "--"
  const pctPart = Number.isFinite(pctNumber) ? ` · ${(pctNumber * 100).toFixed(4)}%` : ""
  return `${dollarsNumber >= 0 ? "+" : ""}${dollarsNumber.toFixed(2)}${pctPart}`
}

function brtiSkipReasons(
  status: Record<string, unknown>,
  attempts: Array<Record<string, unknown>>,
  recentRuns: Array<Record<string, unknown>>,
) {
  const reasons = new Set<string>()
  for (const value of [
    status.skip_reason,
    status.latest_attempt_reason,
    ...attempts.flatMap((attempt) => [attempt.reason, attempt.latest_attempt_reason]),
    ...recentRuns.flatMap((run) => [run.skip_reason, run.latest_attempt_reason]),
  ]) {
    const reason = String(value || "")
    if (reason.startsWith("brti_context_")) reasons.add(reason)
  }
  return Array.from(reasons)
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

function configFormFrom(config?: Record<string, unknown>): ConfigFormValues {
  const values = CONFIG_FIELDS.reduce((current, field) => {
    current[field.key] = text(config?.[field.key], "")
    return current
  }, {} as ConfigFormValues)
  values.market_context_source = text(config?.market_context_source, "coinbase_primary")
  return values
}

function validateConfigForm(values: ConfigFormValues) {
  const numericPayload = {} as Record<ConfigFieldKey, number>
  const errors: ConfigErrors = {}

  for (const field of CONFIG_FIELDS) {
    const raw = values[field.key].trim()
    const value = field.integer ? Number.parseInt(raw, 10) : Number.parseFloat(raw)
    numericPayload[field.key] = value
    if (!raw || !Number.isFinite(value)) {
      errors[field.key] = "Required."
    }
  }
  if (!MARKET_CONTEXT_OPTIONS.some((option) => option.key === values.market_context_source)) {
    errors.market_context_source = "Required."
  }

  for (const key of ["max_order_dollars", "max_market_exposure_dollars", "max_daily_loss_dollars"] as const) {
    if (!errors[key] && numericPayload[key] <= 0) errors[key] = "Must be positive."
  }
  if (!errors.min_edge && (numericPayload.min_edge < 0 || numericPayload.min_edge > 1)) {
    errors.min_edge = "Use 0 through 1."
  }
  if (!errors.min_contract_price && (numericPayload.min_contract_price < 0 || numericPayload.min_contract_price > 1)) {
    errors.min_contract_price = "Use 0 through 1."
  }
  if (!errors.max_markets && (!Number.isInteger(numericPayload.max_markets) || numericPayload.max_markets < 1 || numericPayload.max_markets > 500)) {
    errors.max_markets = "Use 1 through 500."
  }

  const payload = {
    ...numericPayload,
    market_context_source: values.market_context_source,
  }
  return { errors, payload }
}

export function LiveOperations() {
  const { selectedStrategy, selectedStrategyLabel, strategyReady } = useSelectedStrategy()
  const [payload, setPayload] = useState<LivePayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [configForm, setConfigForm] = useState<ConfigFormValues>(EMPTY_CONFIG_FORM)
  const [configDirty, setConfigDirty] = useState(false)
  const [configErrors, setConfigErrors] = useState<ConfigErrors>({})
  const [configSaving, setConfigSaving] = useState(false)
  const [configSaveMessage, setConfigSaveMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setPayload(await apiGet<LivePayload>(`/live?strategy=${encodeURIComponent(selectedStrategy)}`))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load live status")
    } finally {
      setLoading(false)
    }
  }, [selectedStrategy])

  useEffect(() => {
    if (!strategyReady) return
    setPayload(null)
    setConfigDirty(false)
    setConfigSaveMessage(null)
    setConfigErrors({})
    load()
    const id = window.setInterval(load, 15000)
    return () => window.clearInterval(id)
  }, [load, strategyReady])

  const status = useMemo(() => payload?.live_status || {}, [payload?.live_status])
  const marketContext = asRecord(payload?.market_context)
  const latestRunContext = asRecord(marketContext.latest_run)
  const brtiLatest = asRecord(marketContext.brti_latest)
  const coinbaseDiagnostics = asRecord(marketContext.coinbase_diagnostics)
  const config = payload?.active_config
  const thresholdLabel = text(payload?.strategy_metadata?.threshold_label, "Min price")
  const recentRuns = useMemo(() => payload?.recent_runs || [], [payload?.recent_runs])
  const attempts = useMemo(() => {
    const raw = status.recent_attempts
    return Array.isArray(raw) ? raw.map(asRecord).slice().reverse() : []
  }, [status.recent_attempts])
  const recentBrtiSkips = useMemo(
    () => brtiSkipReasons(status, attempts, recentRuns.map(asRecord)),
    [attempts, recentRuns, status],
  )

  useEffect(() => {
    if (!configDirty) {
      setConfigForm(configFormFrom(config))
    }
  }, [config, configDirty])

  const liveOrdersStatus = (() => {
    if (typeof status.live_orders_enabled === "boolean") {
      return status.live_orders_enabled
        ? { value: "Enabled", tone: "good" as Tone }
        : { value: "Disabled", tone: "warn" as Tone }
    }
    if (loading) return { value: "Checking", tone: "warn" as Tone }
    return {
      value: "Unknown",
      tone: error ? "bad" as Tone : "muted" as Tone,
      detail: error ? "API unavailable" : "No live status",
    }
  })()
  const healthStatus = (() => {
    if (payload?.health?.ok === true) return { value: "OK", tone: "good" as Tone }
    if (payload?.health?.ok === false) return { value: "Error", tone: "bad" as Tone }
    if (loading) return { value: "Checking", tone: "warn" as Tone }
    return { value: "Unknown", tone: error ? "bad" as Tone : "warn" as Tone }
  })()
  const portfolioStatus = (() => {
    const balance = payload?.portfolio_balance
    if (!balance) {
      return { value: "--", tone: loading ? "warn" as Tone : "bad" as Tone, detail: "Checking balance" }
    }
    const detail = `Cash ${optionalMoney(balance.cash_dollars)} · Assets ${optionalMoney(balance.assets_dollars)}`
    if (balance.status === "ok") {
      return {
        value: optionalMoney(balance.portfolio_balance_dollars),
        tone: balance.stale ? "warn" as Tone : "good" as Tone,
        detail: balance.stale ? `${detail} · stale` : detail,
      }
    }
    return {
      value: "--",
      tone: "bad" as Tone,
      detail: balance.detail ? `Unavailable: ${balance.detail}` : "Unavailable",
    }
  })()

  const handleConfigChange = (key: ConfigFormKey, value: string) => {
    setConfigForm((current) => ({ ...current, [key]: value }))
    setConfigDirty(true)
    setConfigSaveMessage(null)
    setConfigErrors((current) => ({ ...current, [key]: undefined }))
  }

  const saveConfig = async () => {
    const validated = validateConfigForm(configForm)
    setConfigErrors(validated.errors)
    if (Object.keys(validated.errors).length) return

    setConfigSaving(true)
    setConfigSaveMessage(null)
    try {
      const saved = await apiPost<SaveConfigResponse>(
        `/live/config?strategy=${encodeURIComponent(selectedStrategy)}`,
        { ...validated.payload, strategy: selectedStrategy },
      )
      let refreshed: LivePayload | null = null
      try {
        refreshed = await apiGet<LivePayload>(`/live?strategy=${encodeURIComponent(selectedStrategy)}`)
      } catch {
        refreshed = null
      }
      setPayload((current) => ({
        ...(refreshed ?? current ?? {}),
        active_config: saved.active_config ?? refreshed?.active_config ?? current?.active_config,
        config_history: saved.config_history ?? refreshed?.config_history ?? current?.config_history,
        market_context: refreshed?.market_context ?? {
          ...(current?.market_context ?? {}),
          active_source: saved.active_config?.market_context_source,
          active_source_label: sourceLabel(saved.active_config?.market_context_source),
        },
      }))
      if (saved.active_config) {
        setConfigForm(configFormFrom(saved.active_config))
      }
      setConfigDirty(false)
      setConfigSaveMessage(saved.active_config?.version ? `Saved v${saved.active_config.version}` : "Saved")
    } catch (err) {
      setConfigSaveMessage(err instanceof Error ? err.message : "Save failed")
    } finally {
      setConfigSaving(false)
    }
  }

  return (
    <div className="p-6 space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Live Operations</h1>
          <p className="text-sm text-muted-foreground">
            {selectedStrategyLabel} · {text(payload?.health?.environment, "environment unknown")} · {shortTime(payload?.health?.generated_at_utc)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          <PortfolioStatus value={portfolioStatus.value} tone={portfolioStatus.tone} detail={portfolioStatus.detail} />
          <HeaderStatus label="Live Orders" value={liveOrdersStatus.value} tone={liveOrdersStatus.tone} detail={liveOrdersStatus.detail} />
          <HeaderStatus label="Health" value={healthStatus.value} tone={healthStatus.tone} />
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
        <Metric label="Market" value={text(status.current_market_ticker, "No recent run")} detail={text(status.run_id, "")} />
        <Metric label="Decision" value={text(status.decision_outcome)} detail={text(status.selected_side || status.skip_reason, "")} />
        <Metric label="Risk" value={money(status.daily_loss_used_dollars)} detail={`limit ${money(status.daily_loss_limit_dollars)} · market ${money(status.market_exposure_used_dollars)} / ${money(status.market_exposure_limit_dollars)}`} />
        <Metric label="Execution" value={text(status.latest_attempt_status || status.fill_status, "No attempt")} detail={text(status.latest_attempt_reason || status.fill_status, "")} />
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
          <Panel title="Runtime Config">
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault()
                void saveConfig()
              }}
            >
              <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span>Version</span>
                <span className="font-mono">{text(config?.version)}</span>
              </div>
              <label className="space-y-1 text-sm">
                <span className="block text-xs text-muted-foreground">Market context source</span>
                <select
                  className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/30"
                  name="market_context_source"
                  onChange={(event) => handleConfigChange("market_context_source", event.target.value)}
                  value={configForm.market_context_source}
                >
                  {MARKET_CONTEXT_OPTIONS.map((option) => (
                    <option key={option.key} value={option.key}>{option.label}</option>
                  ))}
                </select>
                {configErrors.market_context_source && (
                  <span className="block text-xs text-destructive">{configErrors.market_context_source}</span>
                )}
              </label>
              <div className="grid grid-cols-2 gap-3">
                {CONFIG_FIELDS.map((field) => (
                  <label key={field.key} className="space-y-1 text-sm">
                    <span className="block text-xs text-muted-foreground">
                      {field.key === "min_contract_price" ? thresholdLabel : field.label}
                    </span>
                    <input
                      className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/30"
                      inputMode="decimal"
                      max={field.max}
                      min={field.min}
                      name={field.key}
                      onChange={(event) => handleConfigChange(field.key, event.target.value)}
                      step={field.step}
                      type="number"
                      value={configForm[field.key]}
                    />
                    {configErrors[field.key] && (
                      <span className="block text-xs text-destructive">{configErrors[field.key]}</span>
                    )}
                  </label>
                ))}
              </div>
              <div className="flex min-h-7 items-center justify-between gap-3">
                <span className={`text-xs ${configSaveMessage === "Saved" || configSaveMessage?.startsWith("Saved v") ? "text-success" : "text-muted-foreground"}`}>
                  {configSaveMessage}
                </span>
                <Button type="submit" size="sm" disabled={!config || configSaving}>
                  <Save className="h-4 w-4" />
                  {configSaving ? "Saving" : "Save"}
                </Button>
              </div>
            </form>
          </Panel>
          <Panel title="Market Context">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Value label="Active source" value={sourceLabel(marketContext.active_source || config?.market_context_source)} />
              <Value label="Run source" value={sourceLabel(latestRunContext.market_context_source)} />
              <Value label="BRTI value" value={optionalNumber(brtiLatest.value)} />
              <Value label="BRTI age" value={seconds(brtiLatest.age_seconds)} />
              <Value label="BRTI health" value={text(brtiLatest.status)} />
              <Value label="Freshness" value={seconds(brtiLatest.freshness_limit_seconds)} />
              <Value label="Basis" value={basisText(coinbaseDiagnostics.basis_dollars, coinbaseDiagnostics.basis_pct)} />
              <Value label="Coinbase diag" value={text(coinbaseDiagnostics.status)} />
            </div>
            <div className="mt-3 border-t border-border pt-3">
              <div className="text-xs text-muted-foreground">Recent BRTI skips</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {recentBrtiSkips.length ? recentBrtiSkips.map((reason) => (
                  <span key={reason} className="rounded-md border border-border bg-background px-2 py-1 font-mono text-xs">
                    {reason}
                  </span>
                )) : (
                  <span className="text-sm text-muted-foreground">--</span>
                )}
              </div>
            </div>
          </Panel>
          <Panel title="Risk">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Value label="Daily used" value={money(status.daily_loss_used_dollars)} />
              <Value label="Daily limit" value={money(status.daily_loss_limit_dollars)} />
              <Value label="Market used" value={money(status.market_exposure_used_dollars)} />
              <Value label="Market limit" value={money(status.market_exposure_limit_dollars)} />
            </div>
          </Panel>
          <Panel title="Recent Runs">
            <div className="space-y-2">
              {recentRuns.length ? recentRuns.map((run, index) => (
                <div key={index} className="text-sm border-t border-border first:border-0 pt-2 first:pt-0">
                  <div className="font-mono text-xs">{text(run.run_id)}</div>
                  <div className="text-muted-foreground">{text(run.decision_outcome)} · {text(run.latest_attempt_reason, "")} · {shortTime(run.generated_at)}</div>
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

function PortfolioStatus({ value, detail, tone }: { value: string; detail: string; tone: Tone }) {
  return (
    <div
      aria-label={`Portfolio: ${value}`}
      className="inline-flex h-7 items-center gap-2 rounded-md border border-border bg-card px-2 text-xs text-muted-foreground"
      title={detail}
    >
      <span>Portfolio</span>
      <span className="font-mono text-foreground">{value}</span>
      <span className={`h-2 w-2 rounded-full ${toneDotClass(tone)}`} />
    </div>
  )
}

function HeaderStatus({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone: Tone }) {
  return (
    <div
      aria-label={`${label}: ${value}`}
      className="inline-flex h-7 items-center gap-2 rounded-md border border-border bg-card px-2 text-xs text-muted-foreground"
      title={detail ? `${value}: ${detail}` : value}
    >
      <span>{label}</span>
      <span className={`h-2 w-2 rounded-full ${toneDotClass(tone)}`} />
    </div>
  )
}

function Metric({ label, value, detail, tone = "muted" }: { label: string; value: string; detail?: string; tone?: Tone }) {
  const toneClass = toneTextClass(tone)
  return (
    <div className="border border-border rounded-lg bg-card p-4 min-h-24">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-2 text-xl font-semibold ${toneClass}`}>{value}</div>
      {detail && <div className="mt-1 text-xs text-muted-foreground truncate">{detail}</div>}
    </div>
  )
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
