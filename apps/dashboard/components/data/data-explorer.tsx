"use client"

import { useEffect, useMemo, useState } from "react"
import { apiGet, apiPost } from "@/lib/alphadb-api"
import { Button } from "@/components/ui/button"
import { Download, RefreshCw, Save } from "lucide-react"

interface DataView {
  name: string
  label: string
  columns: string[]
  default_sort: string
  description: string
}

interface ViewsResponse {
  views: DataView[]
}

interface QueryResult {
  view: DataView
  filters: Record<string, unknown>
  sort: Record<string, unknown>
  limit: number
  schema: Array<{ name: string; type: string }>
  rows: Array<Record<string, unknown>>
  row_count: number
}

function text(value: unknown, fallback = "") {
  if (value === null || value === undefined || value === "") return fallback
  return String(value)
}

export function DataExplorer() {
  const [views, setViews] = useState<DataView[]>([])
  const [selected, setSelected] = useState("decisions")
  const [runId, setRunId] = useState("")
  const [marketTicker, setMarketTicker] = useState("")
  const [status, setStatus] = useState("")
  const [limit, setLimit] = useState(100)
  const [result, setResult] = useState<QueryResult | null>(null)
  const [exportBody, setExportBody] = useState("")
  const [message, setMessage] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const filters = useMemo(() => {
    const next: Record<string, string> = {}
    if (runId.trim()) next.run_id = runId.trim()
    if (marketTicker.trim()) next.market_ticker = marketTicker.trim()
    if (status.trim()) {
      next.status = status.trim()
      next.outcome = status.trim()
    }
    return next
  }, [runId, marketTicker, status])

  const loadViews = async () => {
    const data = await apiGet<ViewsResponse>("/data/views")
    setViews(data.views || [])
  }

  const query = async () => {
    setLoading(true)
    setError(null)
    setMessage("")
    try {
      const params = new URLSearchParams({ limit: String(limit) })
      Object.entries(filters).forEach(([key, value]) => params.set(key, value))
      setResult(await apiGet<QueryResult>(`/data/views/${selected}?${params.toString()}`))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to query data view")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadViews().catch((err) => setError(err instanceof Error ? err.message : "Unable to load views"))
  }, [])

  useEffect(() => {
    query()
  }, [selected])

  const saveToLab = async () => {
    const view = views.find((item) => item.name === selected)
    const data = await apiPost<{ entry: { lab_entry_id: string; title: string } }>(`/data/views/${selected}/save-to-lab`, {
      title: `${view?.label || selected} evidence`,
      filters,
      limit,
    })
    setMessage(`Saved to Lab as ${data.entry.title} (${data.entry.lab_entry_id}).`)
  }

  const exportRows = async (format: "csv" | "json") => {
    const data = await apiPost<{ export: { body: string; row_count: number } }>(
      `/data/views/${selected}/export`,
      { format, filters, limit }
    )
    setExportBody(data.export.body)
    setMessage(`Exported ${data.export.row_count} rows as ${format.toUpperCase()}.`)
  }

  const activeView = views.find((view) => view.name === selected)
  const rows = result?.rows || []
  const columns = result?.schema.map((column) => column.name) || activeView?.columns || []

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Data</h1>
          <p className="text-sm text-muted-foreground">{activeView?.description || "Curated operational views"}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={query} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            Query
          </Button>
          <Button variant="outline" size="sm" onClick={saveToLab} disabled={!result}>
            <Save className="h-4 w-4" />
            Save to Lab
          </Button>
        </div>
      </div>

      {error && <div className="border border-destructive/40 bg-destructive/10 rounded-lg p-3 text-sm text-destructive">{error}</div>}
      {message && <div className="border border-success/40 bg-success/10 rounded-lg p-3 text-sm text-success">{message}</div>}

      <section className="border border-border rounded-lg bg-card p-4">
        <div className="grid gap-3 md:grid-cols-[220px_1fr_1fr_140px]">
          <label className="text-sm">
            <span className="text-muted-foreground">View</span>
            <select
              className="mt-2 h-9 w-full rounded-md border border-border bg-background px-2"
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
            >
              {views.map((view) => (
                <option key={view.name} value={view.name}>{view.label}</option>
              ))}
            </select>
          </label>
          <FilterInput label="Run ID" value={runId} onChange={setRunId} />
          <FilterInput label="Market" value={marketTicker} onChange={setMarketTicker} />
          <label className="text-sm">
            <span className="text-muted-foreground">Limit</span>
            <input
              className="mt-2 h-9 w-full rounded-md border border-border bg-background px-2"
              type="number"
              min={1}
              max={500}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
            />
          </label>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto_auto]">
          <FilterInput label="Status / outcome" value={status} onChange={setStatus} />
          <Button variant="outline" size="sm" className="self-end" onClick={() => exportRows("csv")} disabled={!result}>
            <Download className="h-4 w-4" />
            CSV
          </Button>
          <Button variant="outline" size="sm" className="self-end" onClick={() => exportRows("json")} disabled={!result}>
            <Download className="h-4 w-4" />
            JSON
          </Button>
        </div>
      </section>

      <section className="border border-border rounded-lg overflow-hidden">
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                {columns.map((column) => (
                  <th key={column} className="text-left font-medium text-muted-foreground px-4 py-2 whitespace-nowrap">{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.length ? rows.map((row, index) => (
                <tr key={index} className="border-t border-border">
                  {columns.map((column) => (
                    <td key={column} className="px-4 py-2 max-w-80 truncate font-mono text-xs">
                      {text(row[column], "--")}
                    </td>
                  ))}
                </tr>
              )) : (
                <tr>
                  <td className="px-4 py-10 text-center text-muted-foreground" colSpan={Math.max(columns.length, 1)}>
                    {loading ? "Loading rows..." : "No rows for this view."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {exportBody && (
        <section className="border border-border rounded-lg bg-card p-4">
          <h2 className="text-sm font-medium mb-3">Export</h2>
          <pre className="max-h-64 overflow-auto rounded-md bg-background p-3 text-xs text-muted-foreground">
            {exportBody}
          </pre>
        </section>
      )}
    </div>
  )
}

function FilterInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input
        className="mt-2 h-9 w-full rounded-md border border-border bg-background px-2"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}
