"use client"

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react"
import { apiGet, apiPost } from "@/lib/alphadb-api"
import { Button } from "@/components/ui/button"
import { Field, FieldMessage, Input, Select, fieldLabelClassName } from "@/components/ui/field"
import { MetricSurface, NestedSurface, PanelBody, PanelHeader, PanelSurface } from "@/components/ui/surface"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useSelectedStrategy } from "@/components/strategy/strategy-context"
import { Activity, ChevronDown, ChevronRight, CircleHelp, Eye, EyeOff, GripVertical, RefreshCw, RotateCcw, Save, ShieldAlert, Square } from "lucide-react"

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

interface ResetDailyLimitsResponse {
  ok?: boolean
  live_risk_day?: string
  live_risk_admission_state?: Record<string, unknown>
}

type Tone = "good" | "warn" | "bad" | "muted"

interface LiveEdgeAttribution {
  edge?: number | null
  min_edge?: number | null
  edge_shortfall?: number | null
  edge_margin?: number | null
  edge_cleared?: boolean | null
}

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

const TABLE_TOOLTIPS = {
  details: "Expand a row to inspect order, sizing, risk, and config details.",
  time: "When this order attempt was created or submitted.",
  market: "Kalshi market ticker for the attempted live decision.",
  status: "Recorded attempt status, such as submitted, skipped, or failed.",
  reason: "Primary skip or guard reason recorded by the live worker.",
  edge: "After-fee edge in contract-price percentage points. Positive means fair value is above executable price plus fees.",
  min: "Minimum required after-fee edge from runtime config. 0.00% means require break-even or better.",
  gap: "How far the calculated edge is above or below the configured minimum edge.",
  fill: "Exchange submission or fill lifecycle status for the attempt.",
} as const

const CONFIG_TOOLTIPS = {
  version: "Runtime config version currently active for this strategy.",
  market_context_source: "External price/context source the next fair_value_live run should use.",
  max_order_dollars: "Maximum dollars the live worker may reserve for a single order.",
  max_market_exposure_dollars: "Maximum allowed exposure in one market before new orders are skipped.",
  max_daily_loss_dollars: "Live risk day realized-loss cap. Skips once realized loss reaches this limit.",
  min_edge: "Minimum after-fee edge required before submitting an order. 0.02 means 2 percentage points.",
  min_contract_price: "Lowest executable contract price this strategy is allowed to trade.",
  max_markets: "Maximum number of markets this strategy may act on in one live sweep.",
} as const

const MARKET_CONTEXT_TOOLTIPS = {
  active_source: "Source currently selected in runtime config. Future runs should use this value.",
  run_source: "Source the latest displayed live run actually used. It may lag the active source until another run completes.",
  brti_value: "Latest BRTI index value available to the runtime.",
  brti_age: "How old the latest BRTI context is when this status was generated.",
  brti_health: "Whether the latest BRTI context is usable for live decisions.",
  freshness: "Maximum BRTI age allowed before fair_value_live fails closed with a stale-context skip.",
  basis: "BRTI minus Coinbase reference price, shown in dollars and as a percent of Coinbase.",
  coinbase_diag: "Whether Coinbase reference data is available for diagnostics and basis comparison.",
  recent_brti_skips: "Recent skip reasons caused by missing, stale, or invalid BRTI context.",
} as const

const RISK_TOOLTIPS = {
  daily_used: "Realized loss for this strategy in the current live risk day.",
  daily_limit: "Configured max realized daily loss cap for this strategy.",
  market_used: "Current exposure already used or reserved in this market.",
  market_limit: "Configured per-market exposure cap for this strategy.",
} as const

const ACTIVITY_FEED_LIMIT = 50
const PANEL_LAYOUT_VERSION = 1

const PANEL_IDS = [
  "market",
  "decision",
  "risk-summary",
  "execution",
  "activity-feed",
  "runtime-config",
  "market-context",
  "risk",
  "recent-runs",
] as const

type PanelId = (typeof PANEL_IDS)[number]

interface PanelDefinition {
  label: string
  defaultWidth: number
  defaultHeight: number
  minWidth: number
  minHeight: number
}

interface PanelLayoutItem {
  id: PanelId
  width: number
  height: number
}

const PANEL_DEFINITIONS: Record<PanelId, PanelDefinition> = {
  market: { label: "Market", defaultWidth: 280, defaultHeight: 112, minWidth: 220, minHeight: 96 },
  decision: { label: "Decision", defaultWidth: 280, defaultHeight: 112, minWidth: 220, minHeight: 96 },
  "risk-summary": { label: "Risk summary", defaultWidth: 320, defaultHeight: 112, minWidth: 260, minHeight: 96 },
  execution: { label: "Execution", defaultWidth: 300, defaultHeight: 112, minWidth: 240, minHeight: 96 },
  "activity-feed": { label: "Activity Feed", defaultWidth: 920, defaultHeight: 520, minWidth: 420, minHeight: 260 },
  "runtime-config": { label: "Runtime Config", defaultWidth: 360, defaultHeight: 420, minWidth: 320, minHeight: 320 },
  "market-context": { label: "Market Context", defaultWidth: 360, defaultHeight: 260, minWidth: 320, minHeight: 220 },
  risk: { label: "Risk", defaultWidth: 360, defaultHeight: 170, minWidth: 280, minHeight: 140 },
  "recent-runs": { label: "Recent Runs", defaultWidth: 360, defaultHeight: 260, minWidth: 300, minHeight: 180 },
}

const PANEL_ID_SET = new Set<PanelId>(PANEL_IDS)

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

function isPanelId(value: unknown): value is PanelId {
  return typeof value === "string" && PANEL_ID_SET.has(value as PanelId)
}

function defaultPanelLayout(): PanelLayoutItem[] {
  return PANEL_IDS.map((id) => {
    const definition = PANEL_DEFINITIONS[id]
    return {
      id,
      width: definition.defaultWidth,
      height: definition.defaultHeight,
    }
  })
}

function normalizePanelSize(id: PanelId, width: unknown, height: unknown): PanelLayoutItem {
  const definition = PANEL_DEFINITIONS[id]
  const parsedWidth = Number(width)
  const parsedHeight = Number(height)
  return {
    id,
    width: Math.max(
      definition.minWidth,
      Math.min(1600, Number.isFinite(parsedWidth) ? Math.round(parsedWidth) : definition.defaultWidth),
    ),
    height: Math.max(
      definition.minHeight,
      Math.min(1200, Number.isFinite(parsedHeight) ? Math.round(parsedHeight) : definition.defaultHeight),
    ),
  }
}

function normalizePanelLayout(value: unknown): PanelLayoutItem[] {
  const rawItems = Array.isArray(value)
    ? value
    : Array.isArray(asRecord(value).items)
      ? asRecord(value).items
      : []
  const ordered: PanelLayoutItem[] = []
  const seen = new Set<PanelId>()

  for (const rawItem of rawItems) {
    const item = asRecord(rawItem)
    if (!isPanelId(item.id) || seen.has(item.id)) continue
    ordered.push(normalizePanelSize(item.id, item.width, item.height))
    seen.add(item.id)
  }

  for (const id of PANEL_IDS) {
    if (!seen.has(id)) {
      const definition = PANEL_DEFINITIONS[id]
      ordered.push({
        id,
        width: definition.defaultWidth,
        height: definition.defaultHeight,
      })
    }
  }

  return ordered
}

function normalizeHiddenPanels(value: unknown): PanelId[] {
  const rawHidden = asRecord(value).hidden
  if (!Array.isArray(rawHidden)) return []
  const hidden: PanelId[] = []
  const seen = new Set<PanelId>()

  for (const id of rawHidden) {
    if (!isPanelId(id) || seen.has(id)) continue
    hidden.push(id)
    seen.add(id)
  }

  return hidden
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

function optionalPercent(value: unknown) {
  if (value === null || value === undefined || value === "") return "--"
  const number = Number(value)
  if (!Number.isFinite(number)) return "--"
  return `${(number * 100).toFixed(2)}%`
}

function edgeAttribution(attempt: Record<string, unknown>): LiveEdgeAttribution {
  return asRecord(attempt.live_edge_attribution) as LiveEdgeAttribution
}

function edgeGapText(attribution: LiveEdgeAttribution) {
  const shortfall = Number(attribution.edge_shortfall)
  if (Number.isFinite(shortfall) && shortfall > 0) {
    return `short ${optionalPercent(shortfall)}`
  }
  const margin = Number(attribution.edge_margin)
  if (Number.isFinite(margin)) {
    return `${margin >= 0 ? "+" : ""}${optionalPercent(margin)}`
  }
  const edge = Number(attribution.edge)
  const minEdge = Number(attribution.min_edge)
  if (Number.isFinite(edge) && Number.isFinite(minEdge)) {
    const derivedMargin = edge - minEdge
    if (derivedMargin < 0) return `short ${optionalPercent(-derivedMargin)}`
    return `+${optionalPercent(derivedMargin)}`
  }
  return "--"
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

function attemptKey(attempt: Record<string, unknown>, index: number) {
  return [
    text(attempt.submitted_at || attempt.created_at, "no-time"),
    text(attempt.market_ticker, "no-market"),
    text(attempt.order_id || attempt.client_order_id || attempt.reservation_id, String(index)),
  ].join(":")
}

function reorderPanels(
  layout: PanelLayoutItem[],
  draggedId: PanelId,
  targetId: PanelId,
) {
  if (draggedId === targetId) return layout
  const dragged = layout.find((item) => item.id === draggedId)
  if (!dragged) return layout
  const withoutDragged = layout.filter((item) => item.id !== draggedId)
  const targetIndex = withoutDragged.findIndex((item) => item.id === targetId)
  if (targetIndex < 0) return layout
  const next = [...withoutDragged]
  next.splice(targetIndex, 0, dragged)
  return next
}

function isInteractiveDragTarget(target: EventTarget | null) {
  return target instanceof Element
    ? Boolean(target.closest("button,input,select,textarea,a,[role='button'],[data-no-panel-drag='true']"))
    : false
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
  const [dailyLimitsResetting, setDailyLimitsResetting] = useState(false)
  const [configSaveMessage, setConfigSaveMessage] = useState<string | null>(null)
  const [expandedAttempts, setExpandedAttempts] = useState<Record<string, boolean>>({})
  const [panelLayout, setPanelLayout] = useState<PanelLayoutItem[]>(defaultPanelLayout)
  const [hiddenPanelIds, setHiddenPanelIds] = useState<PanelId[]>([])
  const [layoutLoaded, setLayoutLoaded] = useState(false)
  const [panelMenuOpen, setPanelMenuOpen] = useState(false)
  const [draggingPanelId, setDraggingPanelId] = useState<PanelId | null>(null)
  const panelElements = useRef(new Map<PanelId, HTMLDivElement>())
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const layoutLoadedRef = useRef(false)
  const dragCleanupRef = useRef<(() => void) | null>(null)
  const layoutStorageKey = `alphadb.liveOperations.homeLayout.v${PANEL_LAYOUT_VERSION}.${selectedStrategy}`

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
    return Array.isArray(raw) ? raw.map(asRecord).slice().reverse().slice(0, ACTIVITY_FEED_LIMIT) : []
  }, [status.recent_attempts])
  const totalAttemptCount = Number(status.recent_attempt_count)
  const activityCountLabel = Number.isFinite(totalAttemptCount) && totalAttemptCount > attempts.length
    ? `Last ${attempts.length} of ${totalAttemptCount}`
    : `Last ${attempts.length}`
  const recentBrtiSkips = useMemo(
    () => brtiSkipReasons(status, attempts, recentRuns.map(asRecord)),
    [attempts, recentRuns, status],
  )
  const hiddenPanelSet = useMemo(() => new Set(hiddenPanelIds), [hiddenPanelIds])
  const visiblePanelLayout = useMemo(
    () => panelLayout.filter((item) => !hiddenPanelSet.has(item.id)),
    [hiddenPanelSet, panelLayout],
  )

  useEffect(() => {
    setLayoutLoaded(false)
    try {
      const saved = window.localStorage.getItem(layoutStorageKey)
      const savedState = saved ? JSON.parse(saved) : null
      setPanelLayout(normalizePanelLayout(savedState))
      setHiddenPanelIds(normalizeHiddenPanels(savedState))
    } catch {
      setPanelLayout(defaultPanelLayout())
      setHiddenPanelIds([])
    }
    setPanelMenuOpen(false)
    setLayoutLoaded(true)
  }, [layoutStorageKey])

  useEffect(() => {
    layoutLoadedRef.current = layoutLoaded
  }, [layoutLoaded])

  useEffect(() => () => {
    dragCleanupRef.current?.()
  }, [])

  useEffect(() => {
    if (!layoutLoaded) return
    try {
      window.localStorage.setItem(layoutStorageKey, JSON.stringify({ items: panelLayout, hidden: hiddenPanelIds }))
    } catch {
      // Layout persistence is a convenience; the operator view should still render.
    }
  }, [hiddenPanelIds, layoutLoaded, layoutStorageKey, panelLayout])

  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver((entries) => {
      if (!layoutLoadedRef.current) return
      const sizes = new Map<PanelId, { width: number; height: number }>()
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).dataset.panelId
        if (!isPanelId(id)) continue
        const rect = entry.contentRect
        sizes.set(id, { width: rect.width, height: rect.height })
      }
      if (!sizes.size) return
      setPanelLayout((current) => {
        let changed = false
        const next = current.map((item) => {
          const size = sizes.get(item.id)
          if (!size) return item
          const normalized = normalizePanelSize(item.id, size.width, size.height)
          if (Math.abs(normalized.width - item.width) < 2 && Math.abs(normalized.height - item.height) < 2) {
            return item
          }
          changed = true
          return normalized
        })
        return changed ? next : current
      })
    })
    resizeObserverRef.current = observer
    for (const element of panelElements.current.values()) observer.observe(element)
    return () => {
      observer.disconnect()
      resizeObserverRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!configDirty) {
      setConfigForm(configFormFrom(config))
    }
  }, [config, configDirty])

  const registerPanelElement = useCallback((id: PanelId) => (node: HTMLDivElement | null) => {
    const previous = panelElements.current.get(id)
    if (previous && resizeObserverRef.current) resizeObserverRef.current.unobserve(previous)
    if (!node) {
      panelElements.current.delete(id)
      return
    }
    panelElements.current.set(id, node)
    if (resizeObserverRef.current) resizeObserverRef.current.observe(node)
  }, [])

  const resetPanelLayout = () => {
    setPanelLayout(defaultPanelLayout())
    setHiddenPanelIds([])
    setExpandedAttempts({})
    setPanelMenuOpen(false)
  }

  const hidePanel = (id: PanelId) => {
    setHiddenPanelIds((current) => current.includes(id) ? current : [...current, id])
  }

  const togglePanelVisibility = (id: PanelId) => {
    setHiddenPanelIds((current) => current.includes(id)
      ? current.filter((hiddenId) => hiddenId !== id)
      : [...current, id]
    )
  }

  const beginPanelDrag = (event: ReactMouseEvent<HTMLElement>, id: PanelId) => {
    if (event.button !== 0) return
    const rect = event.currentTarget.getBoundingClientRect()
    const explicitHandle = event.currentTarget instanceof HTMLElement && event.currentTarget.dataset.panelDragHandle
    const inResizeCorner = !explicitHandle && event.clientX >= rect.right - 28 && event.clientY >= rect.bottom - 28
    if (inResizeCorner) return
    event.preventDefault()
    event.stopPropagation()
    dragCleanupRef.current?.()
    setDraggingPanelId(id)

    const originalCursor = document.body.style.cursor
    const originalUserSelect = document.body.style.userSelect
    document.body.style.cursor = "grabbing"
    document.body.style.userSelect = "none"

    const handleMouseMove = (mouseEvent: MouseEvent) => {
      const target = document
        .elementFromPoint(mouseEvent.clientX, mouseEvent.clientY)
        ?.closest("[data-panel-id]")
      const targetId = target?.getAttribute("data-panel-id")
      if (isPanelId(targetId)) {
        setPanelLayout((current) => reorderPanels(current, id, targetId))
      }
    }

    const cleanup = () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", cleanup)
      document.body.style.cursor = originalCursor
      document.body.style.userSelect = originalUserSelect
      dragCleanupRef.current = null
      setDraggingPanelId(null)
    }

    dragCleanupRef.current = cleanup
    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", cleanup, { once: true })
  }

  const toggleAttempt = (key: string) => {
    setExpandedAttempts((current) => ({
      ...current,
      [key]: !current[key],
    }))
  }

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

  const resetDailyLimits = async () => {
    const confirmed = window.confirm(
      "Reset realized daily loss for the current live risk day? Open and pending exposure will remain reserved.",
    )
    if (!confirmed) return

    setDailyLimitsResetting(true)
    setConfigSaveMessage(null)
    try {
      const reset = await apiPost<ResetDailyLimitsResponse>(
        "/live/reset-daily-limits",
        { strategy: selectedStrategy },
      )
      setPayload(await apiGet<LivePayload>(`/live?strategy=${encodeURIComponent(selectedStrategy)}`))
      setConfigDirty(false)
      setConfigSaveMessage(reset.live_risk_day ? `Daily loss reset for ${reset.live_risk_day}` : "Daily loss reset")
    } catch (err) {
      setConfigSaveMessage(err instanceof Error ? err.message : "Reset failed")
    } finally {
      setDailyLimitsResetting(false)
    }
  }

  const panelContent: Record<PanelId, ReactNode> = {
    market: (
      <Metric label="Market" value={text(status.current_market_ticker, "No recent run")} detail={text(status.run_id, "")} />
    ),
    decision: (
      <Metric label="Decision" value={text(status.decision_outcome)} detail={text(status.selected_side || status.skip_reason, "")} />
    ),
    "risk-summary": (
      <Metric label="Risk" value={money(status.daily_loss_used_dollars)} detail={`loss limit ${money(status.daily_loss_limit_dollars)} · market ${money(status.market_exposure_used_dollars)} / ${money(status.market_exposure_limit_dollars)}`} />
    ),
    execution: (
      <Metric label="Execution" value={text(status.latest_attempt_status || status.fill_status, "No attempt")} detail={text(status.latest_attempt_reason || status.fill_status, "")} />
    ),
    "activity-feed": (
      <ActivityFeed
        attempts={attempts}
        countLabel={activityCountLabel}
        expandedAttempts={expandedAttempts}
        onToggleAttempt={toggleAttempt}
      />
    ),
    "runtime-config": (
      <Panel title="Runtime Config">
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            void saveConfig()
          }}
        >
          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <TooltipLabel label="Version" tooltip={CONFIG_TOOLTIPS.version} />
            <span className="font-mono">{text(config?.version)}</span>
          </div>
          <Field>
            <TooltipLabel
              className={fieldLabelClassName}
              label="Market context source"
              tooltip={CONFIG_TOOLTIPS.market_context_source}
            />
            <Select
              aria-label="Market context source"
              aria-invalid={Boolean(configErrors.market_context_source) || undefined}
              name="market_context_source"
              onChange={(event) => handleConfigChange("market_context_source", event.target.value)}
              value={configForm.market_context_source}
            >
              {MARKET_CONTEXT_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>{option.label}</option>
              ))}
            </Select>
            {configErrors.market_context_source && (
              <FieldMessage tone="error">{configErrors.market_context_source}</FieldMessage>
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            {CONFIG_FIELDS.map((field) => (
              <Field key={field.key}>
                <TooltipLabel
                  className={fieldLabelClassName}
                  label={field.key === "min_contract_price" ? thresholdLabel : field.label}
                  tooltip={CONFIG_TOOLTIPS[field.key]}
                />
                <Input
                  aria-label={field.key === "min_contract_price" ? thresholdLabel : field.label}
                  aria-invalid={Boolean(configErrors[field.key]) || undefined}
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
                  <FieldMessage tone="error">{configErrors[field.key]}</FieldMessage>
                )}
              </Field>
            ))}
          </div>
          <div className="flex min-h-7 items-center justify-between gap-3">
            <span className={`text-xs ${configSaveMessage === "Saved" || configSaveMessage?.startsWith("Saved v") || configSaveMessage?.startsWith("Daily loss reset") ? "text-success" : "text-muted-foreground"}`}>
              {configSaveMessage}
            </span>
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" size="sm" disabled={!config || dailyLimitsResetting} onClick={() => void resetDailyLimits()}>
                <RotateCcw className="h-4 w-4" />
                {dailyLimitsResetting ? "Resetting" : "Reset daily"}
              </Button>
              <Button type="submit" size="sm" disabled={!config || configSaving}>
                <Save className="h-4 w-4" />
                {configSaving ? "Saving" : "Save"}
              </Button>
            </div>
          </div>
        </form>
      </Panel>
    ),
    "market-context": (
      <Panel title="Market Context">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Value
            label="Active source"
            tooltip={MARKET_CONTEXT_TOOLTIPS.active_source}
            value={sourceLabel(marketContext.active_source || config?.market_context_source)}
          />
          <Value
            label="Run source"
            tooltip={MARKET_CONTEXT_TOOLTIPS.run_source}
            value={sourceLabel(latestRunContext.market_context_source)}
          />
          <Value label="BRTI value" tooltip={MARKET_CONTEXT_TOOLTIPS.brti_value} value={optionalNumber(brtiLatest.value)} />
          <Value label="BRTI age" tooltip={MARKET_CONTEXT_TOOLTIPS.brti_age} value={seconds(brtiLatest.age_seconds)} />
          <Value label="BRTI health" tooltip={MARKET_CONTEXT_TOOLTIPS.brti_health} value={text(brtiLatest.status)} />
          <Value label="Freshness" tooltip={MARKET_CONTEXT_TOOLTIPS.freshness} value={seconds(brtiLatest.freshness_limit_seconds)} />
          <Value label="Basis" tooltip={MARKET_CONTEXT_TOOLTIPS.basis} value={basisText(coinbaseDiagnostics.basis_dollars, coinbaseDiagnostics.basis_pct)} />
          <Value label="Coinbase diag" tooltip={MARKET_CONTEXT_TOOLTIPS.coinbase_diag} value={text(coinbaseDiagnostics.status)} />
        </div>
        <div className="mt-3 border-t border-border pt-3">
          <TooltipLabel
            className="text-xs text-muted-foreground"
            label="Recent BRTI skips"
            tooltip={MARKET_CONTEXT_TOOLTIPS.recent_brti_skips}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            {recentBrtiSkips.length ? recentBrtiSkips.map((reason) => (
              <span key={reason} className="rounded-md border border-field-border/60 bg-surface-inset px-2 py-1 font-mono text-xs text-foreground">
                {reason}
              </span>
            )) : (
              <span className="text-sm text-muted-foreground">--</span>
            )}
          </div>
        </div>
      </Panel>
    ),
    risk: (
      <Panel title="Risk">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Value label="Daily loss" tooltip={RISK_TOOLTIPS.daily_used} value={money(status.daily_loss_used_dollars)} />
          <Value label="Daily limit" tooltip={RISK_TOOLTIPS.daily_limit} value={money(status.daily_loss_limit_dollars)} />
          <Value label="Market used" tooltip={RISK_TOOLTIPS.market_used} value={money(status.market_exposure_used_dollars)} />
          <Value label="Market limit" tooltip={RISK_TOOLTIPS.market_limit} value={money(status.market_exposure_limit_dollars)} />
        </div>
      </Panel>
    ),
    "recent-runs": (
      <Panel title="Recent Runs">
        <div className="space-y-2">
          {recentRuns.length ? recentRuns.map((run, index) => (
            <NestedSurface key={index} className="px-2 py-1.5 text-sm">
              <div className="font-mono text-xs">{text(run.run_id)}</div>
              <div className="text-muted-foreground">{text(run.decision_outcome)} · {text(run.latest_attempt_reason, "")} · {shortTime(run.generated_at)}</div>
            </NestedSurface>
          )) : (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <ShieldAlert className="h-4 w-4" />
              No recent runs.
            </div>
          )}
        </div>
      </Panel>
    ),
  }

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
          <PanelVisibilityMenu
            hiddenPanelIds={hiddenPanelIds}
            onOpenChange={setPanelMenuOpen}
            onTogglePanel={togglePanelVisibility}
            open={panelMenuOpen}
          />
          <Button variant="outline" size="sm" onClick={resetPanelLayout} title="Reset saved panel layout">
            <RotateCcw className="h-4 w-4" />
            Reset layout
          </Button>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
          <Button
            className="disabled:border-cockpit-risk/35 disabled:bg-cockpit-risk/10 disabled:text-cockpit-risk/70 disabled:opacity-100"
            variant="destructive"
            size="sm"
            disabled
            title="Backend stop skill is not wired yet"
          >
            <Square className="h-4 w-4" />
            Stop
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-cockpit-risk/45 bg-cockpit-risk/10 p-3 text-sm text-cockpit-risk">
          {error}
        </div>
      )}

      <section className="flex flex-wrap items-start gap-3">
        {visiblePanelLayout.length ? visiblePanelLayout.map((item) => (
          <ResizableDraggablePanel
            draggingPanelId={draggingPanelId}
            item={item}
            key={item.id}
            onDragStart={beginPanelDrag}
            onHidePanel={hidePanel}
            registerPanelElement={registerPanelElement}
          >
            {panelContent[item.id]}
          </ResizableDraggablePanel>
        )) : (
          <div className="w-full rounded-lg border border-dashed border-field-border/70 bg-surface-panel p-6 text-sm text-muted-foreground">
            All panels are hidden. Use Panels to restore the view.
          </div>
        )}
      </section>
    </div>
  )
}

function PanelVisibilityMenu({
  hiddenPanelIds,
  onOpenChange,
  onTogglePanel,
  open,
}: {
  hiddenPanelIds: PanelId[]
  onOpenChange: (open: boolean) => void
  onTogglePanel: (id: PanelId) => void
  open: boolean
}) {
  const hiddenSet = new Set(hiddenPanelIds)
  const visibleCount = PANEL_IDS.length - hiddenPanelIds.length
  return (
    <div className="relative" data-no-panel-drag="true">
      <Button
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => onOpenChange(!open)}
        size="sm"
        title="Show or hide home panels"
        type="button"
        variant="outline"
      >
        <Eye className="h-4 w-4" />
        Panels
        <span className="font-mono text-xs text-muted-foreground">{visibleCount}/{PANEL_IDS.length}</span>
      </Button>
      {open && (
        <div className="fixed left-20 right-4 top-44 z-30 overflow-hidden rounded-lg border border-field-border/70 bg-surface-panel text-popover-foreground shadow-2xl sm:absolute sm:left-auto sm:right-0 sm:top-8 sm:w-64">
          <div className="border-b border-border/90 bg-surface-panel-raised px-3 py-2 text-xs font-medium text-muted-foreground">
            Home panels
          </div>
          <div className="max-h-80 overflow-auto p-1">
            {PANEL_IDS.map((id) => (
              <label
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm transition hover:bg-cockpit-accent-soft hover:text-foreground"
                key={id}
              >
                <input
                  checked={!hiddenSet.has(id)}
                  className="size-4 accent-cockpit-accent-border"
                  onChange={() => onTogglePanel(id)}
                  type="checkbox"
                />
                <span>{PANEL_DEFINITIONS[id].label}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ResizableDraggablePanel({
  children,
  draggingPanelId,
  item,
  onDragStart,
  onHidePanel,
  registerPanelElement,
}: {
  children: ReactNode
  draggingPanelId: PanelId | null
  item: PanelLayoutItem
  onDragStart: (event: ReactMouseEvent<HTMLElement>, id: PanelId) => void
  onHidePanel: (id: PanelId) => void
  registerPanelElement: (id: PanelId) => (node: HTMLDivElement | null) => void
}) {
  const definition = PANEL_DEFINITIONS[item.id]
  const dragging = draggingPanelId === item.id
  return (
    <div
      className={`relative cursor-grab rounded-lg transition active:cursor-grabbing ${dragging ? "scale-[0.99] opacity-75 ring-2 ring-cockpit-accent-border/60" : ""}`}
      data-panel-id={item.id}
      onMouseDown={(event) => {
        if (isInteractiveDragTarget(event.target)) return
        onDragStart(event, item.id)
      }}
      ref={registerPanelElement(item.id)}
      style={{
        flex: "0 0 auto",
        height: item.height,
        maxWidth: "100%",
        minHeight: definition.minHeight,
        minWidth: `min(${definition.minWidth}px, 100%)`,
        overflow: "hidden",
        resize: "both",
        width: item.width,
      }}
    >
      <button
        aria-label={`Move ${definition.label} panel`}
        className="absolute right-11 top-2 z-10 inline-flex size-8 touch-none cursor-grab items-center justify-center rounded-md border border-field-border/80 bg-surface-inset/95 text-muted-foreground shadow-lg transition hover:border-cockpit-accent-border hover:bg-cockpit-accent-soft hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cockpit-accent-border/35 active:cursor-grabbing"
        data-panel-drag-handle={item.id}
        onMouseDown={(event) => onDragStart(event, item.id)}
        title={`Drag ${definition.label}`}
        type="button"
      >
        <GripVertical className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        aria-label={`Hide ${definition.label} panel`}
        className="absolute right-2 top-2 z-10 inline-flex size-8 items-center justify-center rounded-md border border-field-border/80 bg-surface-inset/95 text-muted-foreground shadow-lg transition hover:border-cockpit-accent-border hover:bg-cockpit-accent-soft hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cockpit-accent-border/35"
        data-no-panel-drag="true"
        onClick={() => onHidePanel(item.id)}
        title={`Hide ${definition.label}`}
        type="button"
      >
        <EyeOff className="h-4 w-4" aria-hidden="true" />
      </button>
      <div className="h-full min-h-0">{children}</div>
    </div>
  )
}

function ActivityFeed({
  attempts,
  countLabel,
  expandedAttempts,
  onToggleAttempt,
}: {
  attempts: Array<Record<string, unknown>>
  countLabel: string
  expandedAttempts: Record<string, boolean>
  onToggleAttempt: (key: string) => void
}) {
  return (
    <PanelSurface>
      <PanelHeader className="flex items-center justify-between gap-3 pr-20">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-cockpit-accent-border" />
          <h2 className="text-sm font-medium">Activity Feed</h2>
        </div>
        <span className="rounded-md border border-field-border/70 bg-surface-inset px-2 py-1 text-xs text-muted-foreground">
          {countLabel}
        </span>
      </PanelHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="min-w-[980px] w-full text-sm">
          <thead className="sticky top-0 z-[1] border-b border-border/90 bg-surface-panel-raised text-muted-foreground">
            <tr>
              <th className="w-10 px-3 py-2 font-medium">
                <TooltipLabel label="Details" tooltip={TABLE_TOOLTIPS.details} />
              </th>
              <th className="text-left px-4 py-2 font-medium">
                <TooltipLabel label="Time" tooltip={TABLE_TOOLTIPS.time} />
              </th>
              <th className="text-left px-4 py-2 font-medium">
                <TooltipLabel label="Market" tooltip={TABLE_TOOLTIPS.market} />
              </th>
              <th className="text-left px-4 py-2 font-medium">
                <TooltipLabel label="Status" tooltip={TABLE_TOOLTIPS.status} />
              </th>
              <th className="text-left px-4 py-2 font-medium">
                <TooltipLabel label="Reason" tooltip={TABLE_TOOLTIPS.reason} />
              </th>
              <th className="text-right px-4 py-2 font-medium">
                <TooltipLabel label="Edge" tooltip={TABLE_TOOLTIPS.edge} className="ml-auto" />
              </th>
              <th className="text-right px-4 py-2 font-medium">
                <TooltipLabel label="Min" tooltip={TABLE_TOOLTIPS.min} className="ml-auto" />
              </th>
              <th className="text-right px-4 py-2 font-medium">
                <TooltipLabel label="Gap" tooltip={TABLE_TOOLTIPS.gap} className="ml-auto" />
              </th>
              <th className="text-left px-4 py-2 font-medium">
                <TooltipLabel label="Fill" tooltip={TABLE_TOOLTIPS.fill} />
              </th>
            </tr>
          </thead>
          <tbody>
            {attempts.length ? attempts.map((attempt, index) => {
              const key = attemptKey(attempt, index)
              const attribution = edgeAttribution(attempt)
              const expanded = Boolean(expandedAttempts[key])
              return (
                <Fragment key={key}>
                  <tr key={key} className="border-t border-border/80 transition hover:bg-surface-panel-raised/45">
                    <td className="px-3 py-2 align-top">
                      <Button
                        aria-expanded={expanded}
                        aria-label={`${expanded ? "Collapse" : "Expand"} attempt details`}
                        onClick={() => onToggleAttempt(key)}
                        size="icon-xs"
                        title={`${expanded ? "Collapse" : "Expand"} attempt details`}
                        type="button"
                        variant="ghost"
                      >
                        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                      </Button>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">{shortTime(attempt.submitted_at || attempt.created_at)}</td>
                    <td className="px-4 py-2 font-mono text-xs">{text(attempt.market_ticker)}</td>
                    <td className="px-4 py-2">{text(attempt.status)}</td>
                    <td className="px-4 py-2 text-muted-foreground">{text(attempt.reason || attempt.guard_reason, "")}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{optionalPercent(attribution.edge)}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{optionalPercent(attribution.min_edge)}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{edgeGapText(attribution)}</td>
                    <td className="px-4 py-2">{text(attempt.fill_status, "")}</td>
                  </tr>
                  {expanded && (
                    <tr key={`${key}:details`} className="border-t border-border/80 bg-surface-inset">
                      <td colSpan={9} className="px-4 py-3">
                        <AttemptDetails attempt={attempt} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            }) : (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                  No live attempts recorded.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </PanelSurface>
  )
}

function AttemptDetails({ attempt }: { attempt: Record<string, unknown> }) {
  const riskAdmission = asRecord(attempt.risk_admission)
  const configVersion = text(attempt.config_version, "")
  return (
    <div className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
      <ActivityDetail label="Side" value={text(attempt.side)} />
      <ActivityDetail label="Order ID" value={text(attempt.order_id || attempt.client_order_id)} />
      <ActivityDetail label="Contracts" value={text(attempt.sized_contracts || attempt.intended_contracts)} />
      <ActivityDetail label="Ask" value={optionalPercent(attempt.observed_yes_ask)} />
      <ActivityDetail label="Threshold" value={optionalPercent(attempt.yes_ask_threshold)} />
      <ActivityDetail label="Max loss" value={optionalMoney(attempt.max_loss_dollars)} />
      <ActivityDetail label="Risk admission" value={text(riskAdmission.status || riskAdmission.reason)} />
      <ActivityDetail label="Config" value={configVersion ? `v${configVersion}` : text(attempt.config_id)} />
    </div>
  )
}

function ActivityDetail({ label, value }: { label: string; value: string }) {
  return (
    <NestedSurface className="min-w-0 px-2 py-1.5">
      <div className="text-muted-foreground">{label}</div>
      <div className="mt-1 truncate font-mono text-foreground">{value}</div>
    </NestedSurface>
  )
}

function PortfolioStatus({ value, detail, tone }: { value: string; detail: string; tone: Tone }) {
  return (
    <div
      aria-label={`Portfolio: ${value}`}
      className="inline-flex h-7 items-center gap-2 rounded-md border border-field-border/60 bg-surface-panel-raised px-2 text-xs text-muted-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.03)]"
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
      className="inline-flex h-7 items-center gap-2 rounded-md border border-field-border/60 bg-surface-panel-raised px-2 text-xs text-muted-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.03)]"
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
    <MetricSurface>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-2 text-xl font-semibold ${toneClass}`}>{value}</div>
      {detail && <div className="mt-1 text-xs text-muted-foreground truncate">{detail}</div>}
    </MetricSurface>
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
    <PanelSurface>
      <PanelHeader className="pr-20">
        <h2 className="text-sm font-medium">{title}</h2>
      </PanelHeader>
      <PanelBody className="pr-2">
        {children}
      </PanelBody>
    </PanelSurface>
  )
}

function TooltipLabel({ label, tooltip, className = "" }: { label: string; tooltip: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        aria-label={`${label}: ${tooltip}`}
        className={`inline-flex items-center gap-1 rounded-sm text-left text-current underline decoration-dotted underline-offset-4 transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 ${className}`}
        title={tooltip}
        type="button"
      >
        <span>{label}</span>
        <CircleHelp className="h-3 w-3 shrink-0 opacity-70" aria-hidden="true" />
      </TooltipTrigger>
      <TooltipContent side="top" align="start">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  )
}

function Value({ label, value, tooltip }: { label: string; value: string; tooltip?: string }) {
  return (
    <NestedSurface className="flex min-w-0 items-center justify-between gap-3 px-2 py-1.5">
      {tooltip ? (
        <TooltipLabel className="text-muted-foreground" label={label} tooltip={tooltip} />
      ) : (
        <span className="text-muted-foreground">{label}</span>
      )}
      <span className="font-mono text-xs">{value}</span>
    </NestedSurface>
  )
}
