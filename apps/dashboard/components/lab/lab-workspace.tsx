"use client"

import { useEffect, useState } from "react"
import { apiGet, apiPost } from "@/lib/alphadb-api"
import { Button } from "@/components/ui/button"
import { FlaskConical, Lightbulb, RefreshCw, Save, Sparkles } from "lucide-react"

interface LabEntry {
  lab_entry_id: string
  kind: "research_idea" | "experiment"
  title: string
  hypothesis: string
  brief: string
  status: string
  verdict: string | null
  unsupported_reasons: string[]
  closest_templates: string[]
  missing_capabilities: string[]
  dataset_snapshot_id: string | null
  strategy_snapshot_id: string | null
  metrics: Record<string, unknown>
  updated_at: string
}

interface EntriesResponse {
  entries: LabEntry[]
}

interface Insight {
  insight_id: string
  insight_type: string
  text: string
  confidence: number
  related_lab_entry_ids: string[]
}

interface InsightsResponse {
  insights: Insight[]
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

export function LabWorkspace() {
  const [entries, setEntries] = useState<LabEntry[]>([])
  const [insights, setInsights] = useState<Insight[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [title, setTitle] = useState("")
  const [hypothesis, setHypothesis] = useState("")
  const [kind, setKind] = useState<LabEntry["kind"]>("experiment")
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState("")
  const [loading, setLoading] = useState(true)

  const selected = entries.find((entry) => entry.lab_entry_id === selectedId) || entries[0]

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [entryData, insightData] = await Promise.all([
        apiGet<EntriesResponse>("/lab/entries"),
        apiGet<InsightsResponse>("/lab/insights"),
      ])
      setEntries(entryData.entries || [])
      setInsights(insightData.insights || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load Lab")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const saveEntry = async () => {
    setError(null)
    setMessage("")
    try {
      await apiPost("/lab/entries", {
        kind,
        title,
        hypothesis,
        brief: hypothesis,
      })
      setTitle("")
      setHypothesis("")
      setMessage("Saved Lab entry.")
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed")
    }
  }

  const generateInsights = async () => {
    setError(null)
    setMessage("")
    try {
      const data = await apiPost<InsightsResponse>("/lab/insights/generate", {})
      setInsights(data.insights || [])
      setMessage(`Generated ${data.insights?.length || 0} insights.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Insight generation failed")
    }
  }

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Lab</h1>
          <p className="text-sm text-muted-foreground">Research Ideas and Experiments</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={generateInsights}>
            <Sparkles className="h-4 w-4" />
            Insights
          </Button>
        </div>
      </div>

      {error && <div className="border border-destructive/40 bg-destructive/10 rounded-lg p-3 text-sm text-destructive">{error}</div>}
      {message && <div className="border border-success/40 bg-success/10 rounded-lg p-3 text-sm text-success">{message}</div>}

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)_360px]">
        <aside className="border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-medium">Entries</h2>
          </div>
          <div className="divide-y divide-border">
            {entries.length ? entries.map((entry) => (
              <button
                key={entry.lab_entry_id}
                className={`block w-full text-left px-4 py-3 hover:bg-muted/40 ${selected?.lab_entry_id === entry.lab_entry_id ? "bg-muted/50" : ""}`}
                onClick={() => setSelectedId(entry.lab_entry_id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{entry.title}</span>
                  <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">{entry.kind}</span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{entry.status} · {shortTime(entry.updated_at)}</div>
              </button>
            )) : (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                {loading ? "Loading Lab..." : "No Lab entries."}
              </div>
            )}
          </div>
        </aside>

        <main className="space-y-4">
          <section className="border border-border rounded-lg bg-card p-4 space-y-3">
            <h2 className="text-sm font-medium">New Entry</h2>
            <div className="grid gap-3 md:grid-cols-[180px_1fr]">
              <label className="text-sm">
                <span className="text-muted-foreground">Kind</span>
                <select
                  className="mt-2 h-9 w-full rounded-md border border-border bg-background px-2"
                  value={kind}
                  onChange={(event) => setKind(event.target.value as LabEntry["kind"])}
                >
                  <option value="experiment">Experiment</option>
                  <option value="research_idea">Research Idea</option>
                </select>
              </label>
              <label className="text-sm">
                <span className="text-muted-foreground">Title</span>
                <input
                  className="mt-2 h-9 w-full rounded-md border border-border bg-background px-2"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
            </div>
            <label className="block text-sm">
              <span className="text-muted-foreground">Hypothesis</span>
              <textarea
                className="mt-2 min-h-28 w-full resize-y rounded-md border border-border bg-background px-3 py-2"
                value={hypothesis}
                onChange={(event) => setHypothesis(event.target.value)}
              />
            </label>
            <Button size="sm" onClick={saveEntry} disabled={!title.trim()}>
              <Save className="h-4 w-4" />
              Save
            </Button>
          </section>

          <section className="border border-border rounded-lg bg-card p-4">
            {selected ? (
              <div className="space-y-4">
                <div>
                  <h2 className="text-base font-semibold">{selected.title}</h2>
                  <p className="text-sm text-muted-foreground">{selected.kind} · {selected.status}</p>
                </div>
                <p className="whitespace-pre-wrap text-sm text-muted-foreground">{selected.hypothesis || selected.brief || "No hypothesis saved."}</p>
                <div className="grid gap-3 md:grid-cols-2">
                  <Value label="Dataset" value={selected.dataset_snapshot_id || "--"} />
                  <Value label="Strategy snapshot" value={selected.strategy_snapshot_id || "--"} />
                  <Value label="Verdict" value={selected.verdict || "--"} />
                  <Value label="Updated" value={shortTime(selected.updated_at)} />
                </div>
                {!!selected.unsupported_reasons.length && (
                  <ListBlock title="Unsupported" items={selected.unsupported_reasons} />
                )}
                {!!selected.missing_capabilities.length && (
                  <ListBlock title="Missing Capabilities" items={selected.missing_capabilities} />
                )}
              </div>
            ) : (
              <div className="py-12 text-center text-sm text-muted-foreground">Select a Lab entry.</div>
            )}
          </section>
        </main>

        <aside className="border border-border rounded-lg bg-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Lightbulb className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-medium">Insights</h2>
          </div>
          <div className="space-y-3">
            {insights.length ? insights.map((insight) => (
              <div key={insight.insight_id} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs uppercase text-muted-foreground">{insight.insight_type}</span>
                  <span className="font-mono text-xs text-muted-foreground">{Math.round(insight.confidence * 100)}%</span>
                </div>
                <p className="mt-2 text-sm">{insight.text}</p>
              </div>
            )) : (
              <p className="text-sm text-muted-foreground">No insights saved.</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate font-mono text-xs">{value}</div>
    </div>
  )
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground mb-2">{title}</div>
      <ul className="space-y-1 text-sm">
        {items.map((item) => (
          <li key={item} className="rounded-md bg-muted px-2 py-1">{item}</li>
        ))}
      </ul>
    </div>
  )
}
